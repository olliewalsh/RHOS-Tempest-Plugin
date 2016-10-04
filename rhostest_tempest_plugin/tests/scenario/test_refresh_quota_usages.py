# Copyright 2016 Red Hat
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
# Requirements
# 1. Grant remote access rights for database
#    GRANT ALL PRIVILEGES ON *.* TO '<user>'@'%' IDENTIFIED BY '<passowrd>'
#    WITH GRANT OPTION;
#    The above user/password information is stored in /etc/tempest.conf
#
# Parameters required in etc/tempest.conf
#    [whitebox_plugin]
#    nova_db_hostname=
#    nova_db_username=
#    nova_db_password=
#    nova_db_database=
#    [stress]
#    target_controller
#    target_ssh_user
#    target_private_key_path
#
from oslo_log import log as logging
from rhostest_tempest_plugin.lib.mysql import default_client as dbclient
from tempest.api.compute import base
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config
from tempest import exceptions
from tempest.lib.common import ssh
from tempest import test

CONF = config.CONF
LOG = logging.getLogger(__name__)


class RefreshQuotaUsages(base.BaseV2ComputeAdminTest):

    @classmethod
    def setup_clients(cls):
        super(RefreshQuotaUsages, cls).setup_clients()
        cls.servers_client = cls.os_adm.servers_client
        cls.flvclient = cls.os_adm.flavors_client

    @classmethod
    def resource_setup(cls):
        super(RefreshQuotaUsages, cls).resource_setup()

    def _execute_ssh(self, host, ssh_user, ssh_key, command):
        ssh_client = ssh.Client(host, ssh_user, key_filename=ssh_key)
        try:
            output = ssh_client.exec_command(command)
            return output
        except exceptions.SSHExecCommandFailed:
            LOG.error('execute_ssh raise exception. command:%s, host:%s.'
                      % (command, host))
            return False

    def _create_nova_flavor(self, name, ram, vcpus, disk, fid):
        # This function creates a flavor with provided parameters
        flavor = self.flvclient.create_flavor(name=name,
                                              ram=ram,
                                              vcpus=vcpus,
                                              disk=disk,
                                              id=fid)['flavor']
        return flavor

    def _create_nova_instance(self, flavor):
        name = data_utils.rand_name("instance")
        image = CONF.compute.image_ref
        net_id = CONF.network.public_network_id
        networks = [{'uuid': net_id}]
        server = self.servers_client.create_server(name=name,
                                                   imageRef=image,
                                                   flavorRef=flavor,
                                                   networks=networks)['server']
        server_id = server['id']
        waiters.wait_for_server_status(self.servers_client, server_id,
                                       'ACTIVE')
        return server_id

    def _access_nova_db(self, command):
        conn = dbclient.connect()
        try:
            with conn.cursor() as cursor:
                data = ""
                result = cursor.execute(command)
                self.assertGreater(result, 0)
                data = cursor.fetchall()
        finally:
            conn.commit()
            conn.close()
            return data

    def _compare_resource_count(self, source1, source2):
        s1 = dict(source1)
        s2 = dict(source2)
        for key, value in s1.iteritems():
            if value != s2[key]:
                return False
        return True

    def _verify_refresh_quota_usages(self, server_id):
        # Retrieve user-id and project-id for instances created
        dbcommand = """
        SELECT user_id,project_id
        FROM instances
        WHERE uuid = "{}"
        """.format(server_id)
        data = self._access_nova_db(dbcommand)
        for item in data:
            user_id = item[0]
            project_id = item[1]
        # Retrieve the resource count from quota usages table
        dbcommand_select = """
        SELECT resource,in_use
        FROM quota_usages
        WHERE project_id = "{}"
        """.format(project_id)
        data_orig = self._access_nova_db(dbcommand_select)
        # Update quota usage table to fake values to mimic out of
        # sync scenario
        dbcommand_update = """
        UPDATE quota_usages
        SET in_use=99
        WHERE project_id = "{}"
        """.format(project_id)
        data = self._access_nova_db(dbcommand_update)
        data_fake = self._access_nova_db(dbcommand_select)
        # Verify that update work and quota usage table is different
        # from original state
        compare = self._compare_resource_count(data_orig, data_fake)
        if compare:
            return False
        # Trigger quota refresh using nova-manage command.
        cmd = ('nova-manage project quota_usage_refresh '
               '--project %s --user %s' % (project_id, user_id))
        ssh_controller = CONF.stress.target_controller
        ssh_username = CONF.stress.target_ssh_user
        ssh_key = CONF.stress.target_private_key_path
        self._execute_ssh(ssh_controller, ssh_username, ssh_key, cmd)
        # Retrieve resource usage count from quota usage table
        data_synced = self._access_nova_db(dbcommand_select)
        # Verify that resource usage is in sync now
        compare = self._compare_resource_count(data_orig, data_synced)
        if not compare:
            LOG.error('Error in refreshing nova quota_usages')
            return False
        return True

    @test.services('compute')
    def test_refresh_quota_usages(self):
        flavor_name = data_utils.rand_name("test_flavor_")
        flavor_id = data_utils.rand_int_id(start=1000)
        self._create_nova_flavor(name=flavor_name, ram=512, vcpus=2, disk=5,
                                 fid=flavor_id)
        for _ in range(2):
            server = self._create_nova_instance(flavor_id)
        self._verify_refresh_quota_usages(server)

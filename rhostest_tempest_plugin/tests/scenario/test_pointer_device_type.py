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
#    [stress]
#    target_controller
#    target_ssh_user
#    target_private_key_path
#
# Parameters required in /etc/nova/nova.conf
#    pointer_model=ps2mouse
#
from oslo_log import log as logging
from tempest.api.compute import base
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config
from tempest import exceptions
from tempest.lib.common import ssh
from tempest import test

CONF = config.CONF
LOG = logging.getLogger(__name__)


class PointerDeviceTypeFromImages(base.BaseV2ComputeAdminTest):

    @classmethod
    def setup_clients(cls):
        super(PointerDeviceTypeFromImages, cls).setup_clients()
        cls.servers_client = cls.os_adm.servers_client
        cls.flvclient = cls.os_adm.flavors_client
        cls.image_client = cls.os_adm.compute_images_client

    @classmethod
    def resource_setup(cls):
        super(PointerDeviceTypeFromImages, cls).resource_setup()

    def _execute_ssh(self, host, ssh_user, ssh_key, command):
        ssh_client = ssh.Client(host, ssh_user, key_filename=ssh_key)
        try:
            output = ssh_client.exec_command(command)
            return output
        except exceptions.SSHExecCommandFailed:
            LOG.error('execute_ssh raise exception. command:%s, host:%s.'
                      % (command, host))
            return False

    def _set_image_metadata_item(self, image):
        req_metadata = {'hw_pointer_model': 'usbtablet'}
        self.image_client.set_image_metadata(image, req_metadata)
        resp_metadata = (self.image_client.list_image_metadata(image)
                         ['metadata'])
        self.assertEqual(req_metadata, resp_metadata)

    def _create_nova_flavor(self, name, ram, vcpus, disk, fid):
        # This function creates a flavor with provided parameters
        flavor = self.flvclient.create_flavor(name=name,
                                              ram=ram,
                                              vcpus=vcpus,
                                              disk=disk,
                                              id=fid)['flavor']
        return flavor

    def _create_nova_instance(self, flavor, image):
        name = data_utils.rand_name("instance")
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

    def _verify_pointer_device_type_from_images(self, server_id):
        # Retrieve input device from virsh dumpxml
        cmd = """virsh dumpxml {} | grep "input type" """.format(server_id)
        ssh_controller = CONF.stress.target_controller
        ssh_username = CONF.stress.target_ssh_user
        ssh_key = CONF.stress.target_private_key_path
        devices = self._execute_ssh(ssh_controller, ssh_username, ssh_key, cmd)
        # Verify that input device contains tablet and mouse
        tablet = "input type='tablet' bus='usb'"
        mouse = "input type='mouse' bus='ps2'"
        self.assertTrue(tablet in devices)
        self.assertTrue(mouse in devices)

    @test.services('compute')
    def test_pointer_device_type_from_images(self):
        image = CONF.compute.image_ref
        self._set_image_metadata_item(image)
        flavor_name = data_utils.rand_name("test_flavor_")
        flavor_id = data_utils.rand_int_id(start=1000)
        self._create_nova_flavor(name=flavor_name, ram=512, vcpus=2, disk=5,
                                 fid=flavor_id)
        server = self._create_nova_instance(flavor_id, image)
        self._verify_pointer_device_type_from_images(server)

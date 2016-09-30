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
#    pci_alias=
#
from oslo_log import log as logging
from rhostest_tempest_plugin.lib.mysql import default_client as dbclient
from tempest.api.compute import base
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config
from tempest import test


CONF = config.CONF
LOG = logging.getLogger(__name__)


class SRIOVPhysicalFunctionPassthroughTest(base.BaseV2ComputeAdminTest):

    @classmethod
    def setup_clients(cls):
        super(SRIOVPhysicalFunctionPassthroughTest, cls).setup_clients()
        cls.client = cls.os_adm.aggregates_client
        cls.flvclient = cls.os_adm.flavors_client

    @classmethod
    def resource_setup(cls):
        super(SRIOVPhysicalFunctionPassthroughTest, cls).resource_setup()

    def _create_physical_function_flavor(self, name, ram, vcpus, disk, fid,
                                         extraspecs):
        # This function creates a flavor with provided parameters
        flavor = self.flvclient.create_flavor(name=name,
                                              ram=ram,
                                              vcpus=vcpus,
                                              disk=disk,
                                              id=fid)['flavor']
        self.assertEqual(flavor['name'], name)
        self.assertEqual(flavor['vcpus'], vcpus)
        self.assertEqual(flavor['disk'], disk)
        self.assertEqual(flavor['ram'], ram)
        self.assertEqual(int(flavor['id']), fid)
        flv = self.flvclient.set_flavor_extra_spec(flavor['id'],
                                                   **extraspecs)['extra_specs']
        self.assertEqual(flv, extraspecs)
        return flavor

    def _create_physical_function_instance(self, flavor):
        name = data_utils.rand_name("instance")
        image = CONF.compute.image_ref
        server = self.servers_client.create_server(name=name,
                                                   imageRef=image,
                                                   flavorRef=flavor)['server']
        server_id = server['id']
        waiters.wait_for_server_status(self.servers_client, server_id,
                                       'ACTIVE')
        return server_id

    def _get_pcideviceinfo(self, column, value):
        # This function retrieves information such as address and status of
        # physical and virtual functions in the pci_devices table.
        conn = dbclient.connect()
        try:
            with conn.cursor() as cursor:
                cursor = conn.cursor()
                dbcommand = """
                SELECT address,status
                FROM pci_devices
                WHERE {} = "{}"
                """.format(column, value)
                result = cursor.execute(dbcommand)
                self.assertGreater(result, 0)
                data = cursor.fetchall()
        finally:
            conn.close()
            return data

    def _test_physical_function_passthrough(self, ram, vcpus, disk,
                                            pci_alias, device):

        pci_alias_spec = pci_alias + ":" + str(device)
        specs = {"pci_passthrough:alias": pci_alias_spec}
        flavor_name_prefix = 'test_flavor_' + pci_alias + "_"
        flavor_name = data_utils.rand_name(flavor_name_prefix)
        flavor_id = data_utils.rand_int_id(start=1000)
        self._create_physical_function_flavor(name=flavor_name,
                                              ram=ram,
                                              vcpus=vcpus,
                                              disk=disk,
                                              fid=flavor_id,
                                              extraspecs=specs)
        server = self._create_physical_function_instance(flavor_id)
        data_pf = self._get_pcideviceinfo("instance_uuid", server)
        for pf in data_pf:
            pf_address = pf[0]
            pf_status = pf[1]
            if pf_status == "allocated":
                data_vf = self._get_pcideviceinfo("parent_addr", pf_address)
                for vf in data_vf:
                    vf_address = vf[0]
                    vf_status = vf[1]
                    if vf_status != "unavailable":
                        LOG.error('Virtual function %s associated with'
                                  ' physical function %s is in status'
                                  ' %s and not in status'
                                  ' unavailable' % (vf_address,
                                                    pf_address,
                                                    vf_status))
                        return False
            else:
                LOG.error('Physical function %s is in status %s and not in'
                          ' status allocated' % (pf_address,
                                                 pf_status))
                return False
        return True

    @test.services('compute')
    def test_sriov_physical_function_passthrough(self):

        ram = 512
        vcpus = 2
        disk = 5
        device = 2
        pci_alias = CONF.whitebox_plugin.pci_alias
        result = self._test_physical_function_passthrough(ram=ram,
                                                          vcpus=vcpus,
                                                          disk=disk,
                                                          device=device,
                                                          pci_alias=pci_alias)
        self.assertTrue(result)
        device = 1
        result = self._test_physical_function_passthrough(ram=ram,
                                                          vcpus=vcpus,
                                                          disk=disk,
                                                          device=device,
                                                          pci_alias=pci_alias)
        self.assertTrue(result)

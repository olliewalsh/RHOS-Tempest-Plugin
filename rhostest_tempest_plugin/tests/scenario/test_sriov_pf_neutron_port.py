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


class SRIOVPFNeutronPortAssignmentTest(base.BaseV2ComputeAdminTest):

    @classmethod
    def setup_clients(cls):
        super(SRIOVPFNeutronPortAssignmentTest, cls).setup_clients()
        cls.servers_client = cls.os_adm.servers_client
        cls.flvclient = cls.os_adm.flavors_client
        cls.network_client = cls.os_adm.networks_client
        cls.subnets_client = cls.os_adm.subnets_client
        cls.ports_client = cls.os_adm.ports_client

    @classmethod
    def resource_setup(cls):
        super(SRIOVPFNeutronPortAssignmentTest, cls).resource_setup()

    def _create_network(self, shared, network_type, physical_network):
        post_body = {"name": data_utils.rand_name('network-'),
                     "shared": shared,
                     "provider:network_type": network_type,
                     "provider:physical_network": physical_network}
        body = self.network_client.create_network(**post_body)
        network = body['network']
        return network['id']

    def _create_subnet(self, network_id, enable_dhcp, gateway, start, end,
                       cidr):
        post_body = {"name": data_utils.rand_name('subnet-'),
                     "allocation_pools": [{'start': str(start),
                                           'end': str(end)}],
                     "enable_dhcp": enable_dhcp,
                     "gateway_ip": gateway,
                     'ip_version': 4,
                     "cidr": cidr,
                     "network_id": network_id}
        subnet = self.subnets_client.create_subnet(**post_body)
        return subnet

    def _create_port(self, network_id, vnic_type):
        post_body = {"name": data_utils.rand_name('port-'),
                     "binding:vnic_type": vnic_type,
                     "network_id": network_id}
        port = self.ports_client.create_port(**post_body)
        return port

    def _create_physical_function_flavor(self, name, ram, vcpus, disk, fid):
        # This function creates a flavor with provided parameters
        flavor = self.flvclient.create_flavor(name=name,
                                              ram=ram,
                                              vcpus=vcpus,
                                              disk=disk,
                                              id=fid)['flavor']
        return flavor

    def _create_physical_function_instance(self, network_id, flavor, port_id):
        name = data_utils.rand_name("instance")
        image = CONF.compute.image_ref
        networks = [{'port': port_id}, {'uuid': network_id}]
        server = self.servers_client.create_server(name=name,
                                                   imageRef=image,
                                                   flavorRef=flavor,
                                                   networks=networks)['server']
        server_id = server['id']
        waiters.wait_for_server_status(self.servers_client, server_id,
                                       'ACTIVE')
        return server_id

    def _get_port_binding_profile(self, port_id, field):
        body = self.ports_client.show_port(port_id)
        port = body['port']
        return port[field]

    def _get_pcidevice_info(self, column, value):
        # This function retrieves information such as address and status of
        # physical and virtual functions in the pci_devices table.
        conn = dbclient.connect()
        try:
            with conn.cursor() as cursor:
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

    def _verify_pf_neutron_port_binding(self, port_id, server_id):
        binding_profile = self._get_port_binding_profile(port_id,
                                                         'binding:profile')
        pci_info = self._get_pcidevice_info("instance_uuid", server_id)
        for pf in pci_info:
            pf_address = pf[0]
            pf_status = pf[1]
            if pf_status != "allocated":
                LOG.error('Physical function %s is in status %s and not in'
                          ' status allocated' % (pf_address,
                                                 pf_status))
                return False
            else:
                if str(pf_address) not in str(binding_profile):
                    LOG.error('PCI device information in Nova and'
                              ' and Binding profile information in'
                              ' Neutron mismatch')
                    return False
        return True

    @test.services('compute')
    def test_sriov_physical_neutron_port_assignment(self):
        network_id = self._create_network(shared=True,
                                          network_type="vlan",
                                          physical_network="physnet")
        self._create_subnet(network_id=network_id,
                            enable_dhcp=True,
                            gateway="1.0.5.1",
                            start="1.0.5.2",
                            end="1.0.5.100",
                            cidr="1.0.5.0/24")
        body = self._create_port(network_id=network_id,
                                 vnic_type="direct-physical")
        port = body['port']
        flavor_name = data_utils.rand_name("test_flavor_")
        flavor_id = data_utils.rand_int_id(start=1000)
        self._create_physical_function_flavor(name=flavor_name,
                                              ram=512, vcpus=2,
                                              disk=5,
                                              fid=flavor_id)
        server = self._create_physical_function_instance(network_id, flavor_id,
                                                         port['id'])
        result = self._verify_pf_neutron_port_binding(port['id'], server)
        self.assertTrue(result)

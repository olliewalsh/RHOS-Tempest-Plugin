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
#
# Parameters required in etc/tempest.conf
#    [compute_private_config]
#    target_controller=
#    target_ssh_user=
#    target_private_key_path=

from oslo_log import log as logging
from rhostest_tempest_plugin import base
from rhostest_tempest_plugin.services import clients
from tempest.common.utils import data_utils
from tempest import config
from tempest import test

CONF = config.CONF
LOG = logging.getLogger(__name__)


class LibvirtPerfEventsTest(base.BaseRHOSTest):

    @classmethod
    def setup_clinets(cls):
        super(LibvirtPerfEventsTest, cls).setup_clients()
        cls.servers_client = cls.os_adm.servers_client

    def _get_perf_section(self, server_id):
        # Retrieve the server's hypervizor hostname
        server = self.servers_client.show_server(server_id)['server']
        hostname = server['OS-EXT-SRV-ATTR:host']
        hypers = self.os_adm.hypervisor_client.list_hypervisors(
            detail=True)['hypervisors']
        compute_node_address = None
        for hypervisor in hypers:
            if hypervisor['service']['host'] == hostname:
                compute_node_address = hypervisor['host_ip']
        self.assertIsNotNone(compute_node_address)

        # Retrieve input device from virsh dumpxml
        virshxml_client = clients.VirshXMLClient(compute_node_address)
        output = virshxml_client.dumpxml(server_id)

        perf_section = parse_xml(output)
        return perf_section

    @test.services('compute')
    def test_libvirt_perf_events(self):
        server = self._create_nova_instance()
        perf_section = self._get_perf_section()
        enabled_perf_events = CONF.compute_private_group.enabled_perf_events

        if enabled_perf_events is None:
            self.assertIsNone(perf_section)
        elif "cmt" in enabled_perf_events:
            self.assertIn(perf_section, '<event enabled="yes" name="cmt" />')
        elif "mbml" in enabled_perf_events:
            self.assertIn(perf_section, '<event enabled="yes" name="mbml" />')
        elif "mbmt" in enabled_perf_events:
            self.assertIn(perf_section, '<event enabled="yes" name="mbmt" />')

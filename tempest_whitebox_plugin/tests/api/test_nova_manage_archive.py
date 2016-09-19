# Copyright 2016
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


from tempest import config
from tempest.lib.cli import base as clibase

from tempest_whitebox_plugin.tests.api import base
from tempest_whitebox_plugin.whitebox.mysql import default_client as dbclient


CONF = config.CONF


class NovaManageTest(base.BaseTempestWhiteboxPlugin):
    """nova-manage related tests

    These tests require to be run as root on the controller node
    """

    @classmethod
    def setup_clients(cls):
        super(NovaManageTest, cls).setup_clients()
        cls.client = cls.servers_client

    def test_nova_manage_db_archive(self):
        for _ in range(5):
            server = self.create_test_server()
            self.client.delete_server(server['id'])

        novaclient = clibase.CLIClient(
            username=CONF.auth.admin_username,
            password=CONF.auth.admin_password,
            tenant_name=CONF.auth.admin_project_name
        )

        novaclient.nova_manage('db',
                               params='archive_deleted_rows --max_rows 5')

        cursor = dbclient.connect().cursor()
        cursor.execute(
            "select id,uuid,deleted from nova.instances where deleted != 0;"
        )

        self.assertLessEqual(len(cursor.fetchall(), 5))

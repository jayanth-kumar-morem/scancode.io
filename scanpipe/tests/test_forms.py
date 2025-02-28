# SPDX-License-Identifier: Apache-2.0
#
# http://nexb.com and https://github.com/nexB/scancode.io
# The ScanCode.io software is licensed under the Apache License version 2.0.
# Data generated with ScanCode.io is provided as-is without warranties.
# ScanCode is a trademark of nexB Inc.
#
# You may not use this software except in compliance with the License.
# You may obtain a copy of the License at: http://apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# Data Generated with ScanCode.io is provided on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied. No content created from
# ScanCode.io should be considered or used as legal advice. Consult an Attorney
# for any legal advice.
#
# ScanCode.io is a free software code scanning tool from nexB Inc. and others.
# Visit https://github.com/nexB/scancode.io for support and download.

from unittest import mock

from django.test import TestCase

from scanpipe.forms import InputsBaseForm
from scanpipe.forms import ProjectForm
from scanpipe.forms import ProjectSettingsForm
from scanpipe.models import Project


class ScanPipeFormsTest(TestCase):
    def setUp(self):
        self.project1 = Project.objects.create(name="Analysis")

    @mock.patch("requests.get")
    def test_scanpipe_forms_inputs_base_form_input_urls(self, mock_get):
        data = {
            "input_urls": "https://example.com/archive.zip",
        }

        mock_get.side_effect = Exception
        form = InputsBaseForm(data=data)
        self.assertFalse(form.is_valid())
        expected = {"input_urls": ["Could not fetch: https://example.com/archive.zip"]}
        self.assertEqual(expected, form.errors)

        mock_get.side_effect = None
        mock_get.return_value = mock.Mock(
            content=b"\x00",
            headers={},
            status_code=200,
            url="url/archive.zip",
        )
        form = InputsBaseForm(data=data)
        self.assertTrue(form.is_valid())
        form.handle_inputs(project=self.project1)
        self.assertEqual(["archive.zip"], self.project1.input_files)
        expected = {"archive.zip": "https://example.com/archive.zip"}
        self.assertEqual(expected, self.project1.input_sources)

    def test_scanpipe_forms_project_form_name(self):
        data = {
            "name": "  Test   Name   ",
            "pipeline": "scan_codebase",
        }
        form = ProjectForm(data=data)
        self.assertTrue(form.is_valid())
        obj = form.save()
        self.assertEqual("Test Name", obj.name)

    def test_scanpipe_forms_project_settings_form_update_name_and_notes(self):
        data = {
            "name": "new name",
            "notes": "some notes",
        }
        form = ProjectSettingsForm(data=data, instance=self.project1)
        self.assertTrue(form.is_valid())
        project = form.save()
        self.assertEqual(data["name"], project.name)
        self.assertEqual(data["notes"], project.notes)

    def test_scanpipe_forms_project_settings_form_set_initial_from_settings_field(self):
        form = ProjectSettingsForm()
        self.assertTrue(form.fields["extract_recursively"].initial)

        self.assertEqual({}, self.project1.settings)
        form = ProjectSettingsForm(instance=self.project1)
        self.assertTrue(form.fields["extract_recursively"].initial)

        self.project1.settings = {"extract_recursively": False}
        self.project1.save()
        form = ProjectSettingsForm(instance=self.project1)
        self.assertFalse(form.fields["extract_recursively"].initial)

    def test_scanpipe_forms_project_settings_form_update_project_settings(self):
        data = {
            "name": self.project1.name,
            "extract_recursively": False,
            "ignored_patterns": "*.ext\ndir/*",
            "scancode_license_score": 10,
        }
        form = ProjectSettingsForm(data=data, instance=self.project1)
        self.assertTrue(form.is_valid())
        project = form.save()

        expected = {
            "extract_recursively": False,
            "ignored_patterns": ["*.ext", "dir/*"],
            "attribution_template": "",
            "scancode_license_score": 10,
        }
        self.assertEqual(expected, project.settings)
        expected = {
            "extract_recursively": False,
            "ignored_patterns": ["*.ext", "dir/*"],
            "scancode_license_score": 10,
        }
        self.assertEqual(expected, project.get_env())

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

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path
from unittest import mock
from unittest import skipIf

from django.conf import settings
from django.test import TestCase
from django.test import tag

from packageurl import PackageURL
from scancode.cli_test_utils import purl_with_fake_uuid

from scanpipe import pipes
from scanpipe.models import DiscoveredPackage
from scanpipe.models import Project
from scanpipe.pipelines import Pipeline
from scanpipe.pipelines import is_pipeline
from scanpipe.pipelines import root_filesystems
from scanpipe.pipes import output
from scanpipe.pipes import scancode
from scanpipe.pipes.input import copy_input
from scanpipe.tests import FIXTURES_REGEN
from scanpipe.tests import package_data1
from scanpipe.tests.pipelines.do_nothing import DoNothing
from scanpipe.tests.pipelines.profile_step import ProfileStep
from scanpipe.tests.pipelines.steps_as_attribute import StepsAsAttribute

from_docker_image = os.environ.get("FROM_DOCKER_IMAGE")


class ScanPipePipelinesTest(TestCase):
    def test_scanpipe_pipeline_class_pipeline_name_attribute(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("do_nothing")
        pipeline_instance = DoNothing(run)
        self.assertEqual("do_nothing", pipeline_instance.pipeline_name)

    def test_scanpipe_pipelines_class_get_info(self):
        expected = {
            "description": "Description section of the doc string.",
            "summary": "Do nothing, in 2 steps.",
            "steps": [
                {"name": "step1", "doc": "Step1 doc."},
                {"name": "step2", "doc": "Step2 doc."},
            ],
        }
        self.assertEqual(expected, DoNothing.get_info())

        expected = {
            "summary": "Profile a step using the @profile decorator.",
            "description": "",
            "steps": [
                {"name": "step", "doc": ""},
            ],
        }
        self.assertEqual(expected, ProfileStep.get_info())

    def test_scanpipe_pipelines_class_get_summary(self):
        expected = "Do nothing, in 2 steps."
        self.assertEqual(expected, DoNothing.get_summary())

        expected = "Profile a step using the @profile decorator."
        self.assertEqual(expected, ProfileStep.get_summary())

    def test_scanpipe_pipeline_class_log(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("do_nothing")
        pipeline = run.make_pipeline_instance()
        pipeline.log("Event1")
        pipeline.log("Event2")

        run.refresh_from_db()
        self.assertIn("Event1", run.log)
        self.assertIn("Event2", run.log)

    def test_scanpipe_pipeline_class_execute(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("do_nothing")
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode)
        self.assertEqual("", out)

        run.refresh_from_db()
        self.assertIn("Pipeline [do_nothing] starting", run.log)
        self.assertIn("Step [step1] starting", run.log)
        self.assertIn("Step [step1] completed", run.log)
        self.assertIn("Step [step2] starting", run.log)
        self.assertIn("Step [step2] completed", run.log)
        self.assertIn("Pipeline completed", run.log)

    def test_scanpipe_pipeline_class_execute_with_exception(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("raise_exception")
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(1, exitcode)
        self.assertTrue(out.startswith("Error message"))
        self.assertIn("Traceback:", out)
        self.assertIn("in execute", out)
        self.assertIn("step(self)", out)
        self.assertIn("in raise_exception", out)
        self.assertIn("raise ValueError", out)

        run.refresh_from_db()
        self.assertIn("Pipeline [raise_exception] starting", run.log)
        self.assertIn("Step [raise_exception_step] starting", run.log)
        self.assertIn("Pipeline failed", run.log)

    def test_scanpipe_pipeline_class_save_errors_context_manager(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("do_nothing")
        pipeline = run.make_pipeline_instance()
        self.assertEqual(project1, pipeline.project)

        with pipeline.save_errors(Exception):
            raise Exception("Error message")

        message = project1.projectmessages.get()
        self.assertEqual("do_nothing", message.model)
        self.assertEqual({}, message.details)
        self.assertEqual("Error message", message.description)
        self.assertIn('raise Exception("Error message")', message.traceback)

    def test_scanpipe_pipelines_is_pipeline(self):
        self.assertFalse(is_pipeline(None))
        self.assertFalse(is_pipeline(Pipeline))
        self.assertTrue(is_pipeline(DoNothing))

        class SubSubClass(DoNothing):
            pass

        self.assertTrue(is_pipeline(SubSubClass))

    def test_scanpipe_pipelines_class_get_graph(self):
        expected = [
            {"doc": "Step1 doc.", "name": "step1"},
            {"doc": "Step2 doc.", "name": "step2"},
        ]
        self.assertEqual(expected, DoNothing.get_graph())

    def test_scanpipe_pipelines_profile_decorator(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("profile_step")
        pipeline_instance = run.make_pipeline_instance()

        exitcode, out = pipeline_instance.execute()
        self.assertEqual(0, exitcode)

        run.refresh_from_db()
        self.assertIn("Profiling results at", run.log)
        self.assertIn("Pipeline completed", run.log)

        self.assertEqual(1, len(project1.output_root))
        output_file = project1.output_root[0]
        self.assertTrue(output_file.startswith("profile-"))
        self.assertTrue(output_file.endswith(".html"))

    def test_scanpipe_pipelines_class_get_steps(self):
        expected = (
            DoNothing.step1,
            DoNothing.step2,
        )
        self.assertEqual(expected, DoNothing.get_steps())

        expected = (StepsAsAttribute.step1,)
        with warnings.catch_warnings(record=True) as caught_warnings:
            self.assertEqual(expected, StepsAsAttribute.get_steps())
            self.assertEqual(len(caught_warnings), 1)
            caught_warning = caught_warnings[0]

        expected = (
            f"Defining ``steps`` as a tuple is deprecated in {StepsAsAttribute} "
            f"Use a ``steps(cls)`` classmethod instead."
        )
        self.assertEqual(expected, str(caught_warning.message))

    def test_scanpipe_pipelines_class_env_loaded_from_config_file(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("do_nothing")
        pipeline = run.make_pipeline_instance()
        self.assertEqual({}, pipeline.env)

        config_file = project1.input_path / settings.SCANCODEIO_CONFIG_FILE
        config_file.write_text("{*this is not valid yml*}")
        pipeline = run.make_pipeline_instance()
        self.assertEqual({}, pipeline.env)

        config_file.write_text("extract_recursively: true")
        pipeline = run.make_pipeline_instance()
        self.assertEqual({"extract_recursively": True}, pipeline.env)

    def test_scanpipe_pipelines_class_flag_ignored_resources(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("do_nothing")
        pipeline = run.make_pipeline_instance()
        self.assertIsNone(pipeline.env.get("ignored_patterns"))

        project1.settings.update({"ignored_patterns": "*.ext"})
        project1.save()
        pipeline = run.make_pipeline_instance()

        with mock.patch("scanpipe.pipes.flag.flag_ignored_patterns") as mock_flag:
            mock_flag.return_value = None
            pipeline.flag_ignored_resources()
        mock_flag.assert_called_with(project1, patterns="*.ext")


class RootFSPipelineTest(TestCase):
    def test_scanpipe_rootfs_pipeline_extract_input_files_errors(self):
        project1 = Project.objects.create(name="Analysis")
        run = project1.add_pipeline("root_filesystems")
        pipeline_instance = root_filesystems.RootFS(run)

        # Create 2 files in the input/ directory to generate error twice
        project1.move_input_from(tempfile.mkstemp()[1])
        project1.move_input_from(tempfile.mkstemp()[1])
        self.assertEqual(2, len(project1.input_files))

        with mock.patch("scanpipe.pipes.scancode.extract_archive") as extract_archive:
            extract_archive.return_value = ["Error"]
            pipeline_instance.extract_input_files_to_codebase_directory()

        error = project1.projectmessages.get()
        self.assertEqual("Error\nError", error.description)


def sort_for_os_compatibility(scan_data):
    """
    Sort the ``scan_data`` files and relations in place. Return ``scan_data``.
    """
    if files := scan_data.get("files"):
        files.sort(key=lambda x: x["path"])

    if relations := scan_data.get("relations"):
        relations.sort(key=lambda x: x["to_resource"])

    return scan_data


@tag("slow")
class PipelinesIntegrationTest(TestCase):
    """
    Set of integration tests to ensure the proper output for each built-in Pipelines.
    """

    # Un-comment the following to display full diffs:
    # maxDiff = None
    data_location = Path(__file__).parent / "data"
    exclude_from_diff = [
        "start_timestamp",
        "end_timestamp",
        "date",
        "duration",
        "input",
        "compliance_alert",
        "policy",
        "tool_version",
        "other_tools",
        "created_date",
        "log",
        "uuid",
        "size",  # directory sizes are OS dependant
        "--json-pp",
        "--processes",
        "--verbose",
        # system_environment differs between systems
        "system_environment",
        "file_type",
        # mime type and is_script are inconsistent across systems
        "mime_type",
        "is_script",
        "notes",
        "settings",
        "description",
    ]

    def _without_keys(self, data, exclude_keys):
        """
        Return the `data` excluding the provided `exclude_keys`.
        """
        if isinstance(data, list):
            return [self._without_keys(entry, exclude_keys) for entry in data]

        if isinstance(data, dict):
            return {
                key: self._without_keys(value, exclude_keys)
                if type(value) in [list, dict]
                else value
                for key, value in data.items()
                if key not in exclude_keys
            }

        return data

    def purl_fields_with_fake_uuid(self, value, key):
        purl_name = "fixed-name-for-testing-5642512d1758"
        purl_namespace = "fixed-namespace-for-testing-5642512d1758"
        if key == "name":
            return purl_name
        elif key == "namespace":
            return purl_namespace
        elif key == "purl" or key == "for_packages":
            purl_old = PackageURL.from_string(value)
            if purl_old.type != "local-files":
                return purl_with_fake_uuid(value)

            purl = PackageURL(
                name=purl_name,
                namespace=purl_namespace,
                type="local-files",
                version=purl_old.version,
                qualifiers=purl_old.qualifiers,
                subpath=purl_old.subpath,
            )
            return purl.to_string()

    def _normalize_package_uids(self, data):
        """
        Return the `data`, where any `package_uid` value has been normalized
        with `purl_with_fake_uuid()`
        """
        if isinstance(data, list):
            return [self._normalize_package_uids(entry) for entry in data]

        if isinstance(data, dict):
            is_local_files = False
            if data.get("type") and data["type"] == "local-files":
                is_local_files = True
            normalized_data = {}
            for key, value in data.items():
                if isinstance(value, (list, dict)):
                    value = self._normalize_package_uids(value)
                if (
                    key in ("package_uid", "dependency_uid", "for_package_uid")
                    and value
                ):
                    value = purl_with_fake_uuid(value)
                if key == "for_packages" and value:
                    value = [
                        self.purl_fields_with_fake_uuid(package_uid, key)
                        for package_uid in value
                    ]
                if is_local_files and key in ("name", "namespace", "purl") and value:
                    value = self.purl_fields_with_fake_uuid(value, key)
                normalized_data[key] = value
            return normalized_data

        return data

    def assertPipelineResultEqual(
        self, expected_file, result_file, regen=FIXTURES_REGEN
    ):
        """
        Set `regen` to True to regenerate the expected results.
        """
        result_json = json.loads(Path(result_file).read_text())
        result_json = self._normalize_package_uids(result_json)
        result_data = self._without_keys(result_json, self.exclude_from_diff)
        result_data = sort_for_os_compatibility(result_data)

        if regen:
            expected_file.write_text(json.dumps(result_data, indent=2))

        expected_json = json.loads(expected_file.read_text())
        expected_json = self._normalize_package_uids(expected_json)
        expected_data = self._without_keys(expected_json, self.exclude_from_diff)
        expected_data = sort_for_os_compatibility(expected_data)

        self.assertEqual(expected_data, result_data)

    @skipIf(from_docker_image, "Random failure in the Docker context.")
    def test_scanpipe_scan_package_pipeline_integration_test(self):
        pipeline_name = "scan_package"
        project1 = Project.objects.create(name="Analysis")

        input_location = self.data_location / "is-npm-1.0.0.tgz"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(4, project1.codebaseresources.count())
        self.assertEqual(1, project1.discoveredpackages.count())
        self.assertEqual(1, project1.discovereddependencies.count())

        scancode_file = project1.get_latest_output(filename="scancode")
        expected_file = self.data_location / "is-npm-1.0.0_scan_package.json"
        self.assertPipelineResultEqual(expected_file, scancode_file)

        summary_file = project1.get_latest_output(filename="summary")
        expected_file = self.data_location / "is-npm-1.0.0_scan_package_summary.json"
        self.assertPipelineResultEqual(expected_file, summary_file)

        # Ensure that we only have one instance of is-npm in `key_files_packages`
        summary_data = json.loads(Path(summary_file).read_text())
        key_files_packages = summary_data.get("key_files_packages", [])
        self.assertEqual(1, len(key_files_packages))
        key_file_package = key_files_packages[0]
        key_file_package_purl = key_file_package.get("purl", "")
        self.assertEqual("pkg:npm/is-npm@1.0.0", key_file_package_purl)

    @skipIf(from_docker_image, "Random failure in the Docker context.")
    def test_scanpipe_scan_package_pipeline_integration_multiple_packages_test(self):
        pipeline_name = "scan_package"
        project1 = Project.objects.create(name="Analysis")

        input_location = self.data_location / "multiple-is-npm-1.0.0.tar.gz"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(9, project1.codebaseresources.count())
        self.assertEqual(2, project1.discoveredpackages.count())
        self.assertEqual(2, project1.discovereddependencies.count())

        scancode_file = project1.get_latest_output(filename="scancode")
        expected_file = self.data_location / "multiple-is-npm-1.0.0_scan_package.json"
        # Do not override the regen as this file is generated in regen_test_data
        self.assertPipelineResultEqual(expected_file, scancode_file)

        summary_file = project1.get_latest_output(filename="summary")
        expected_file = (
            self.data_location / "multiple-is-npm-1.0.0_scan_package_summary.json"
        )
        self.assertPipelineResultEqual(expected_file, summary_file)

    def test_scanpipe_scan_codebase_pipeline_integration_test(self):
        pipeline_name = "scan_codebase"
        project1 = Project.objects.create(name="Analysis")

        filename = "is-npm-1.0.0.tgz"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(6, project1.codebaseresources.count())
        self.assertEqual(1, project1.discoveredpackages.count())
        self.assertEqual(1, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "is-npm-1.0.0_scan_codebase.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    def test_scanpipe_scan_codebase_packages_does_not_create_packages(self):
        pipeline_name = "scan_codebase_packages"
        project1 = Project.objects.create(name="Analysis")

        filename = "is-npm-1.0.0.tgz"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(6, project1.codebaseresources.count())
        self.assertEqual(0, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

    def test_scanpipe_scan_codebase_can_process_wheel(self):
        pipeline_name = "scan_codebase"
        project1 = Project.objects.create(name="Analysis")

        filename = "daglib-0.6.0-py3-none-any.whl"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(11, project1.codebaseresources.count())
        self.assertEqual(2, project1.discoveredpackages.count())
        self.assertEqual(8, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = (
            self.data_location / "daglib-0.6.0-py3-none-any.whl_scan_codebase.json"
        )
        self.assertPipelineResultEqual(expected_file, result_file)

    @skipIf(sys.platform != "linux", "Expected results are inconsistent across OS")
    def test_scanpipe_docker_pipeline_alpine_integration_test(self):
        pipeline_name = "docker"
        project1 = Project.objects.create(name="Analysis")

        filename = "alpine_3_15_4.tar.gz"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(510, project1.codebaseresources.count())
        self.assertEqual(14, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "alpine_3_15_4_scan_codebase.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    def test_scanpipe_docker_pipeline_does_not_report_errors_for_broken_symlinks(self):
        pipeline_name = "docker"
        project1 = Project.objects.create(name="Analysis")

        filename = "minitag.tar"
        input_location = self.data_location / "image-with-symlinks" / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        project_messages = project1.projectmessages.all()
        self.assertEqual(1, len(project_messages))
        self.assertEqual("Distro not found.", project_messages[0].description)

        result_file = output.to_json(project1)
        expected_file = (
            self.data_location
            / "image-with-symlinks"
            / (filename + "-expected-scan.json")
        )
        self.assertPipelineResultEqual(expected_file, result_file)

    @skipIf(sys.platform != "linux", "RPM related features only supported on Linux.")
    def test_scanpipe_docker_pipeline_rpm_integration_test(self):
        pipeline_name = "docker"
        project1 = Project.objects.create(name="Analysis")

        filename = "centos.tar.gz"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(29, project1.codebaseresources.count())
        self.assertEqual(101, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "centos_scan_codebase.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    def test_scanpipe_docker_pipeline_debian_integration_test(self):
        pipeline_name = "docker"
        project1 = Project.objects.create(name="Analysis")

        filename = "debian.tar.gz"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(16, project1.codebaseresources.count())
        self.assertEqual(2, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "debian_scan_codebase.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    def test_scanpipe_docker_pipeline_distroless_debian_integration_test(self):
        pipeline_name = "docker"
        project1 = Project.objects.create(name="Analysis")

        filename = "gcr_io_distroless_base.tar.gz"
        input_location = self.data_location / filename
        project1.copy_input_from(input_location)
        project1.add_input_source(filename, "https://download.url", save=True)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(2458, project1.codebaseresources.count())
        self.assertEqual(6, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "gcr_io_distroless_base_scan_codebase.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    def test_scanpipe_rootfs_pipeline_integration_test(self):
        pipeline_name = "root_filesystems"
        project1 = Project.objects.create(name="Analysis")

        input_location = self.data_location / "basic-rootfs.tar.gz"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(16, project1.codebaseresources.count())
        self.assertEqual(2, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "basic-rootfs_root_filesystems.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    def test_scanpipe_load_inventory_pipeline_integration_test(self):
        pipeline_name = "load_inventory"
        project1 = Project.objects.create(name="Tool: scancode-toolkit")

        input_location = self.data_location / "asgiref-3.3.0_toolkit_scan.json"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(18, project1.codebaseresources.count())
        self.assertEqual(2, project1.discoveredpackages.count())
        self.assertEqual(4, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = (
            self.data_location / "asgiref-3.3.0_load_inventory_expected.json"
        )
        self.assertPipelineResultEqual(expected_file, result_file)

        # Using the ScanCode.io JSON output as the input
        project2 = Project.objects.create(name="Tool: scanpipe")

        input_location = self.data_location / "asgiref-3.3.0_scanpipe_output.json"
        project2.copy_input_from(input_location)

        run = project2.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(18, project2.codebaseresources.count())
        self.assertEqual(2, project2.discoveredpackages.count())
        self.assertEqual(4, project2.discovereddependencies.count())

    @mock.patch("scanpipe.pipes.vulnerablecode.is_available")
    @mock.patch("scanpipe.pipes.vulnerablecode.is_configured")
    @mock.patch("scanpipe.pipes.vulnerablecode.bulk_search_by_purl")
    def test_scanpipe_find_vulnerabilities_pipeline_integration_test(
        self, mock_bulk_search_by_purl, mock_is_configured, mock_is_available
    ):
        pipeline_name = "find_vulnerabilities"
        project1 = Project.objects.create(name="Analysis")
        package1 = DiscoveredPackage.create_from_data(project1, package_data1)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()
        mock_is_configured.return_value = False
        mock_is_available.return_value = False
        exitcode, out = pipeline.execute()
        self.assertEqual(1, exitcode, msg=out)
        self.assertIn("VulnerableCode is not configured.", out)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()
        mock_is_configured.return_value = True
        mock_is_available.return_value = True
        vulnerability_data = [
            {
                "purl": "pkg:deb/debian/adduser@3.118?arch=all",
                "affected_by_vulnerabilities": [
                    {
                        "vulnerability_id": "VCID-cah8-awtr-aaad",
                        "summary": "An issue was discovered.",
                    },
                ],
            },
            {
                "purl": "pkg:deb/debian/adduser@3.118?qualifiers=1",
                "affected_by_vulnerabilities": [
                    {
                        "vulnerability_id": "VCID-cah8-awtr-aaad",
                        "summary": "An issue was discovered.",
                    },
                ],
            },
        ]
        mock_bulk_search_by_purl.return_value = vulnerability_data

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        package1.refresh_from_db()
        expected = vulnerability_data[0]["affected_by_vulnerabilities"]
        self.assertEqual(expected, package1.affected_by_vulnerabilities)

    def test_scanpipe_inspect_manifest_pipeline_integration_test(self):
        pipeline_name = "inspect_manifest"
        project1 = Project.objects.create(name="Analysis")

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        project1.move_input_from(tempfile.mkstemp()[1])
        exitcode, out = pipeline.execute()
        self.assertEqual(1, exitcode, msg=out)
        self.assertIn("No package type found for", out)

    @mock.patch("scanpipe.pipes.resolve.resolve_dependencies")
    def test_scanpipe_inspect_manifest_pipeline_pypi_integration_test(
        self, resolve_dependencies
    ):
        pipeline_name = "inspect_manifest"
        project1 = Project.objects.create(name="Analysis")

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        resolve_dependencies.return_value = mock.Mock(packages=[])
        project1.move_input_from(tempfile.mkstemp(suffix="requirements.txt")[1])
        exitcode, out = pipeline.execute()
        self.assertEqual(1, exitcode, msg=out)
        self.assertIn("No packages could be resolved", out)

        resolve_dependencies.return_value = mock.Mock(packages=[package_data1])
        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(1, project1.discoveredpackages.count())
        discoveredpackage = project1.discoveredpackages.get()
        exclude_fields = ["qualifiers", "release_date", "size"]
        for field_name, value in package_data1.items():
            if value and field_name not in exclude_fields:
                self.assertEqual(value, getattr(discoveredpackage, field_name))

    def test_scanpipe_inspect_manifest_pipeline_aboutfile_integration_test(self):
        pipeline_name = "inspect_manifest"
        project1 = Project.objects.create(name="Analysis")

        input_location = (
            self.data_location / "manifests" / "Django-4.0.8-py3-none-any.whl.ABOUT"
        )
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(1, project1.discoveredpackages.count())
        discoveredpackage = project1.discoveredpackages.get()
        self.assertEqual("pypi", discoveredpackage.type)
        self.assertEqual("django", discoveredpackage.name)
        self.assertEqual("4.0.8", discoveredpackage.version)
        self.assertEqual("bsd-new", discoveredpackage.declared_license_expression)

    def test_scanpipe_inspect_manifest_pipeline_spdx_integration_test(self):
        pipeline_name = "inspect_manifest"
        project1 = Project.objects.create(name="Analysis")

        input_location = self.data_location / "manifests" / "toml.spdx.json"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(1, project1.discoveredpackages.count())
        discoveredpackage = project1.discoveredpackages.get()
        self.assertEqual("pypi", discoveredpackage.type)
        self.assertEqual("toml", discoveredpackage.name)
        self.assertEqual("0.10.2", discoveredpackage.version)
        self.assertEqual("https://github.com/uiri/toml", discoveredpackage.homepage_url)
        self.assertEqual("MIT", discoveredpackage.extracted_license_statement)
        self.assertEqual("mit", discoveredpackage.declared_license_expression)

    def test_scanpipe_inspect_manifest_pipeline_cyclonedx_integration_test(self):
        pipeline_name = "inspect_manifest"
        project1 = Project.objects.create(name="Analysis")

        input_location = self.data_location / "cyclonedx/nested.cdx.json"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(3, project1.discoveredpackages.count())
        packages = project1.discoveredpackages.all()
        expected_data = {
            "pkg:pypi/toml@0.10.2?extension=tar.gz": {
                "type": "pypi",
                "name": "toml",
                "version": "0.10.2",
                "extracted_license_statement": "OFL-1.1\nApache-2.0",
                "declared_license_expression": "ofl-1.1 OR apache-2.0",
                "homepage_url": "https://cyclonedx.org/website",
                "bug_tracking_url": "https://cyclonedx.org/issue-tracker",
                "vcs_url": "https://cyclonedx.org/vcs",
                "filename": "",
            },
            "pkg:pypi/billiard@3.6.3.0": {
                "type": "pypi",
                "name": "billiard",
                "version": "3.6.3.0",
                "extracted_license_statement": "BSD-3-Clause",
                "declared_license_expression": "bsd-new",
                "homepage_url": "",
                "bug_tracking_url": "",
                "vcs_url": "",
                "extra_data": "",
                "filename": "",
            },
            "pkg:pypi/fictional@9.10.2": {
                "type": "pypi",
                "name": "fictional",
                "version": "9.10.2",
                "extracted_license_statement": (
                    "LGPL-3.0-or-later"
                    " AND "
                    "LicenseRef-scancode-openssl-exception-lgpl3.0plus"
                ),
                "declared_license_expression": (
                    "lgpl-3.0-plus AND openssl-exception-lgpl-3.0-plus"
                ),
                "homepage_url": "https://home.page",
                "bug_tracking_url": "",
                "vcs_url": "",
                "extra_data": "",
                "filename": "package.zip",
            },
        }

        for package in packages:
            expected = expected_data.get(str(package))
            self.assertEqual(expected["type"], package.type)
            self.assertEqual(expected["name"], package.name)
            self.assertEqual(expected["version"], package.version)
            self.assertEqual(expected["homepage_url"], package.homepage_url)
            self.assertEqual(
                expected["extracted_license_statement"],
                package.extracted_license_statement,
            )
            self.assertEqual(
                expected["declared_license_expression"],
                package.declared_license_expression,
            )
            self.assertEqual(expected["filename"], package.filename)

    @mock.patch("scanpipe.pipes.purldb.request_post")
    def test_scanpipe_deploy_to_develop_pipeline_integration_test(self, mock_request):
        mock_request.return_value = None
        pipeline_name = "deploy_to_develop"
        project1 = Project.objects.create(name="Analysis")

        jar_location = self.data_location / "d2d" / "jars"
        project1.copy_input_from(jar_location / "from-flume-ng-node-1.9.0.zip")
        project1.copy_input_from(jar_location / "to-flume-ng-node-1.9.0.zip")

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(57, project1.codebaseresources.count())
        self.assertEqual(18, project1.codebaserelations.count())
        self.assertEqual(1, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = self.data_location / "flume-ng-node-d2d.json"
        self.assertPipelineResultEqual(expected_file, result_file)

    @mock.patch("scanpipe.pipes.purldb.request_post")
    def test_scanpipe_deploy_to_develop_pipeline_with_about_file(self, mock_request):
        mock_request.return_value = None
        pipeline_name = "deploy_to_develop"
        project1 = Project.objects.create(name="Analysis")

        data_dir = self.data_location / "d2d" / "about_files"
        project1.copy_input_from(data_dir / "from-with-about-file.zip")
        project1.copy_input_from(data_dir / "to-with-jar.zip")

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertEqual(44, project1.codebaseresources.count())
        self.assertEqual(31, project1.codebaserelations.count())
        self.assertEqual(2, project1.discoveredpackages.count())
        self.assertEqual(0, project1.discovereddependencies.count())

        result_file = output.to_json(project1)
        expected_file = data_dir / "expected.json"
        self.assertPipelineResultEqual(expected_file, result_file)

        self.assertEqual(1, project1.projectmessages.count())
        message = project1.projectmessages.get()
        self.assertEqual("map_about_files", message.model)
        expected = (
            "Resource paths listed at about_resource is not found in the to/ codebase"
        )
        self.assertIn(expected, message.description)

    @mock.patch("scanpipe.pipes.purldb.request_post")
    @mock.patch("scanpipe.pipes.purldb.is_available")
    def test_scanpipe_populate_purldb_pipeline_integration_test(
        self, mock_is_available, mock_request_post
    ):
        pipeline_name1 = "load_inventory"
        pipeline_name2 = "populate_purldb"
        project1 = Project.objects.create(name="Utility: PurlDB")

        input_location = self.data_location / "asgiref-3.3.0_toolkit_scan.json"
        project1.copy_input_from(input_location)

        run = project1.add_pipeline(pipeline_name1)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        def mock_request_post_return(url, data, headers, timeout):
            payload = json.loads(data)
            return {
                "queued_packages_count": len(payload["packages"]),
                "queued_packages": payload["packages"],
                "unqueued_packages_count": 1,
                "unqueued_packages": [],
                "unsupported_packages_count": 1,
                "unsupported_packages": [],
            }

        mock_request_post.side_effect = mock_request_post_return
        mock_is_available.return_value = True

        run = project1.add_pipeline(pipeline_name2)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertIn("Populating PurlDB with 2 PURLs from DiscoveredPackage", run.log)
        self.assertIn("Successfully queued 2 PURLs for indexing in PurlDB", run.log)
        self.assertIn("1 PURLs were already present in PurlDB index queue", run.log)
        self.assertIn("Couldn't index 1 unsupported PURLs", run.log)

    @mock.patch("scanpipe.pipes.purldb.request_post")
    @mock.patch("scanpipe.pipes.purldb.is_available")
    def test_scanpipe_populate_purldb_pipeline_integration_without_assembly(
        self, mock_is_available, mock_request_post
    ):
        pipeline_name = "populate_purldb"
        project1 = Project.objects.create(name="Utility: PurlDB")

        def mock_request_post_return(url, data, headers, timeout):
            payload = json.loads(data)
            return {
                "queued_packages_count": len(payload["packages"]),
                "queued_packages": payload["packages"],
                "unqueued_packages_count": 1,
                "unqueued_packages": [],
                "unsupported_packages_count": 1,
                "unsupported_packages": [],
            }

        mock_request_post.side_effect = mock_request_post_return
        mock_is_available.return_value = True

        package_json_location = self.data_location / "manifests" / "package.json"
        copy_input(package_json_location, project1.codebase_path)
        pipes.collect_and_create_codebase_resources(project1)

        scancode.scan_for_application_packages(project1, assemble=False)

        run = project1.add_pipeline(pipeline_name)
        pipeline = run.make_pipeline_instance()

        exitcode, out = pipeline.execute()
        self.assertEqual(0, exitcode, msg=out)

        self.assertIn("Populating PurlDB with 7 detected PURLs", run.log)
        self.assertIn("Successfully queued 7 PURLs for indexing in PurlDB", run.log)
        self.assertIn("1 PURLs were already present in PurlDB index queue", run.log)
        self.assertIn("Couldn't index 1 unsupported PURLs", run.log)

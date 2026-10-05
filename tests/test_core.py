from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

from arii.domain import AnalysisSpec, DatasetSpec, ValidationSpec
from arii.execution import (
    ClusterProfile, LocalRBackend, RJob, SlurmBackend, SlurmResources,
)
from arii.remote_runner import launcher_command, merge_permutation_results
from arii.residual_tests import build_residual_tests, paired_residual_tests
from arii.system_resources import SystemResources, recommended_workers
from arii.r_bridge import find_rscript, r_subprocess_environment
from arii.resources import asset_path, worker_path
from arii.project_file import fingerprint_file, load_project, save_project
from arii.metadata import export_metadata_template, import_metadata
from arii.export_results import export_numeric_results, export_plsda_results
from arii.metrics import binary_roc, mean_external_scores, sensitivity_specificity_curve
from arii.loading_values import backscaled_loading_values
from arii.spectral_csv import inspect_spectral_csv
from arii.omics_matrix import OmicsMatrixSummary, inspect_omics_matrix
from arii.styles import ClassStyle
from arii.ssh_access import UnknownHostKey, _trust_host_key, _write_managed_key, known_hosts_path


def _r_runtime_available() -> bool:
    if os.environ.get("ARII_SKIP_R_TESTS") == "1":
        return False
    try:
        find_rscript()
    except FileNotFoundError:
        return False
    return True


class RemoteRunnerCommandTests(unittest.TestCase):
    def test_source_launch_uses_python_module(self) -> None:
        program, arguments = launcher_command(
            Path("request.json"), executable="python.exe", frozen=False
        )
        self.assertEqual(program, "python.exe")
        self.assertEqual(arguments, ["-m", "arii.remote_runner", "request.json"])

    def test_frozen_launch_dispatches_inside_arii_without_opening_gui(self) -> None:
        program, arguments = launcher_command(
            Path("request.json"), executable="Arii.exe", frozen=True
        )
        self.assertEqual(program, "Arii.exe")
        self.assertEqual(arguments, ["--arii-remote-runner", "request.json"])


class PackagedResourceTests(unittest.TestCase):
    def test_source_workers_and_icon_are_resolved(self) -> None:
        self.assertEqual(worker_path("pca_worker.R").name, "pca_worker.R")
        self.assertEqual(asset_path("icons/arii-256.png").name, "arii-256.png")

    def test_unknown_worker_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "desconocido"):
            worker_path("arbitrary.R")

    def test_explicit_rscript_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Rscript.exe"
            executable.touch()
            with patch.dict(os.environ, {"ARII_RSCRIPT": str(executable)}):
                self.assertEqual(find_rscript(), executable)

    def test_windows_r_environment_removes_posix_locale_values(self) -> None:
        with patch.dict(os.environ, {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}):
            environment = r_subprocess_environment(
                "C:/Program Files/R/R-4.5.2/bin/Rscript.exe",
                platform_name="nt",
            )
        self.assertNotIn("LC_ALL", environment)
        self.assertNotIn("LANG", environment)

    def test_bundled_windows_x64_rscript_uses_portable_r_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installation = Path(directory)
            executable = (
                installation / "runtime" / "R" / "bin" / "x64" / "Rscript.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("arii.r_bridge.installation_root", return_value=installation):
                environment = r_subprocess_environment(
                    executable, platform_name="nt"
                )

        expected_home = (installation / "runtime" / "R").resolve()
        self.assertEqual(Path(environment["R_HOME"]).resolve(), expected_home)
        self.assertEqual(
            Path(environment["R_LIBS_SITE"]), expected_home / "library"
        )


class ExecutionProfileTests(unittest.TestCase):
    def test_managed_ed25519_key_is_encrypted_and_loadable(self) -> None:
        import paramiko

        profile = ClusterProfile(
            profile_id="managed-test", display_name="Prueba",
            host="cluster.example", username="researcher", scheduler="slurm",
            remote_workspace="/home/researcher/arii",
            authentication="arii_managed_key",
        )
        credential: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"LOCALAPPDATA": directory}
        ), patch(
            "keyring.get_password",
            side_effect=lambda _service, _account: credential.get("password"),
        ), patch(
            "keyring.set_password",
            side_effect=lambda _service, _account, password: credential.__setitem__(
                "password", password
            ),
        ):
            key_path, public_key = _write_managed_key(profile)
            private_key = paramiko.Ed25519Key.from_private_key_file(
                str(key_path), password=credential["password"]
            )
        self.assertTrue(public_key.startswith("ssh-ed25519 "))
        self.assertEqual(private_key.get_name(), "ssh-ed25519")

    def test_confirmed_host_key_is_persisted_for_nonstandard_port(self) -> None:
        import paramiko

        host_key = paramiko.RSAKey.generate(1024)
        unknown = UnknownHostKey(
            lookup_name="[cluster.example]:2222",
            algorithm=host_key.get_name(),
            fingerprint="SHA256:test",
            key_base64=host_key.get_base64(),
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"LOCALAPPDATA": directory}
        ):
            _trust_host_key(unknown)
            saved = paramiko.HostKeys(str(known_hosts_path()))
        self.assertIn("[cluster.example]:2222", saved)

    def test_cluster_profile_round_trip_never_contains_a_secret(self) -> None:
        profile = ClusterProfile(
            profile_id="university", display_name="Clúster institucional",
            host="login.example.edu", username="researcher", scheduler="slurm",
            remote_workspace="/scratch/researcher/arii", account="chemistry",
        )
        restored = ClusterProfile.from_dict(profile.to_dict())
        self.assertEqual(restored, profile)
        self.assertNotIn("password", restored.to_dict())
        self.assertNotIn("private_key", restored.to_dict())

    def test_cluster_profile_rejects_secrets_and_unsafe_workspace(self) -> None:
        base = {
            "profile_id": "cluster", "display_name": "Clúster",
            "host": "cluster.example", "username": "user", "scheduler": "slurm",
            "remote_workspace": "/scratch/user/arii",
        }
        with self.assertRaises(ValueError):
            ClusterProfile.from_dict({**base, "password": "do-not-store"})
        with self.assertRaises(ValueError):
            ClusterProfile.from_dict({**base, "remote_workspace": "/"})
        pageant_profile = ClusterProfile.from_dict(
            {**base, "authentication": "pageant"}
        )
        self.assertEqual(pageant_profile.authentication, "pageant")

    def test_local_backend_builds_worker_contract(self) -> None:
        job = RJob(Path("worker.R"), Path("job.json"), Path("result.json"))
        command = LocalRBackend().command_for(job)
        self.assertTrue(command.program.lower().endswith(("rscript", "rscript.exe")))
        self.assertEqual(command.arguments, ("worker.R", "job.json", "result.json"))

    def test_slurm_backend_builds_closed_sbatch_script(self) -> None:
        profile = ClusterProfile(
            profile_id="university", display_name="Clúster",
            host="login.example.edu", username="researcher", scheduler="slurm",
            remote_workspace="/scratch/researcher/arii", account="chemistry",
            partition="cpu", qos="normal",
        )
        submission = SlurmBackend(profile).build_submission(
            "perm-20260829", "permutation_worker.R",
            SlurmResources(cpus=4, memory_mb=8192, walltime_minutes=150),
        )
        self.assertIn("#SBATCH --cpus-per-task=4", submission.script)
        self.assertIn("#SBATCH --time=02:30:00", submission.script)
        self.assertIn("#SBATCH --account=chemistry", submission.script)
        self.assertIn("/bin/Rscript permutation_worker.R job.json result.json", submission.script)
        self.assertIn('cd -- "$SLURM_SUBMIT_DIR"', submission.script)
        self.assertIn("ARII_PARALLEL_WORKERS", submission.script)
        self.assertIn("OPENBLAS_NUM_THREADS=1", submission.script)
        self.assertNotIn("ssh", submission.script.lower())
        self.assertTrue(submission.result_path.endswith("/result.json"))

    def test_slurm_backend_rejects_commands_and_unknown_workers(self) -> None:
        profile = ClusterProfile(
            profile_id="cluster", display_name="Clúster", host="host",
            username="user", scheduler="slurm", remote_workspace="/work/user/arii",
        )
        backend = SlurmBackend(profile)
        with self.assertRaises(ValueError):
            backend.build_submission("job;rm", "permutation_worker.R", SlurmResources())
        with self.assertRaises(ValueError):
            backend.build_submission("job-1", "custom-command.sh", SlurmResources())

    def test_distributed_permutation_script_uses_independent_slurm_job(self) -> None:
        profile = ClusterProfile(
            profile_id="cluster", display_name="Clúster", host="host",
            username="user", scheduler="slurm", remote_workspace="/work/user/arii",
            partition="cpu",
        )
        submission = SlurmBackend(profile).build_permutation_chunk_submission(
            "perm-1", SlurmResources(cpus=8, nodes=3, memory_mb=12000),
            task_index=1, task_count=3,
        )
        self.assertNotIn("srun", submission.script)
        self.assertIn("ARII_DISTRIBUTED_TASKS=3", submission.script)
        self.assertIn("ARII_DISTRIBUTED_INDEX=1", submission.script)
        self.assertIn("partial-result-1.json", submission.script)

    def test_merges_distributed_permutations_in_original_order(self) -> None:
        def partial(indices, values, task):
            return {
                "permutations": 4,
                "permutation_indices": indices,
                "observed": {"r2y": .8, "q2y": .7, "ber": .1, "auc_macro": .9},
                "null": {name: values for name in ("r2y", "q2y", "auc_macro")}
                | {"ber": values},
                "correlation_to_original": values,
                "null_rejected_fraction": [0] * len(indices),
                "timing": {
                    "total_seconds": 2, "observed_seconds": 1,
                    "permutation_seconds": [1] * len(indices),
                    "parallel_workers": 2, "distributed_index": task,
                },
            }
        merged = merge_permutation_results([
            partial([1, 3], [.1, .3], 0), partial([2, 4], [.2, .4], 1)
        ])
        self.assertEqual(merged["null"]["q2y"], [.1, .2, .3, .4])
        self.assertEqual(merged["timing"]["parallel_workers"], 4)
        self.assertEqual(merged["empirical_p"]["q2y"], .2)

    def test_merge_accepts_machine_precision_differences_in_observed_metrics(self) -> None:
        def partial(index, observed_r2y):
            values = [.1]
            return {
                "permutations": 2, "permutation_indices": [index],
                "observed": {
                    "r2y": observed_r2y, "q2y": .7,
                    "ber": .1, "auc_macro": .9,
                },
                "null": {name: values for name in ("r2y", "q2y", "ber", "auc_macro")},
                "correlation_to_original": values,
                "null_rejected_fraction": [0],
                "timing": {
                    "total_seconds": 1, "observed_seconds": .1,
                    "permutation_seconds": [.5], "parallel_workers": 1,
                },
            }

        merged = merge_permutation_results([
            partial(1, .8), partial(2, .8 - np.finfo(float).eps)
        ])
        self.assertEqual(merged["observed"]["r2y"], .8)

    def test_merge_rejects_material_observed_metric_differences(self) -> None:
        def partial(index, observed_r2y):
            return {
                "permutations": 2, "permutation_indices": [index],
                "observed": {
                    "r2y": observed_r2y, "q2y": .7,
                    "ber": .1, "auc_macro": .9,
                },
                "null": {
                    name: [.1] for name in ("r2y", "q2y", "ber", "auc_macro")
                },
                "correlation_to_original": [.1], "null_rejected_fraction": [0],
                "timing": {
                    "total_seconds": 1, "observed_seconds": .1,
                    "permutation_seconds": [.5], "parallel_workers": 1,
                },
            }

        with self.assertRaisesRegex(ValueError, "tolerancia numérica"):
            merge_permutation_results([partial(1, .8), partial(2, .7)])

    def test_merges_residual_comparison_across_distributed_tasks(self) -> None:
        def partial(indices, values):
            residual = {
                "class_levels": ["A", "B"],
                "observed_standardized_ssq": {
                    mode: {"global": .2, "A": .2, "B": .2}
                    for mode in ("calibration", "cross_validated")
                },
                "null_standardized_ssq": {
                    mode: {scope: values for scope in ("global", "A", "B")}
                    for mode in ("calibration", "cross_validated")
                },
                "observed_error_by_sample": {
                    mode: [[.1, .1], [.2, .2]]
                    for mode in ("calibration", "cross_validated")
                },
                "null_error_sum_by_sample": {
                    mode: [[.3, .3], [.4, .4]]
                    for mode in ("calibration", "cross_validated")
                },
                "tests": {},
            }
            return {
                "permutations": 4, "permutation_indices": indices, "seed": 123,
                "observed": {"r2y": .8, "q2y": .7, "ber": .1, "auc_macro": .9},
                "null": {name: values for name in ("r2y", "q2y", "ber", "auc_macro")},
                "correlation_to_original": values,
                "null_rejected_fraction": [0] * len(indices),
                "residual_comparison": residual,
                "timing": {
                    "total_seconds": 2, "observed_seconds": 1,
                    "permutation_seconds": [1] * len(indices), "parallel_workers": 1,
                },
            }

        merged = merge_permutation_results([
            partial([1, 3], [.1, .3]), partial([2, 4], [.2, .4])
        ])
        residual = merged["residual_comparison"]
        self.assertEqual(
            residual["null_standardized_ssq"]["cross_validated"]["global"],
            [.1, .2, .3, .4],
        )
        self.assertEqual(residual["evaluated_permutations"], 4)
        self.assertIn("wilcoxon", residual["tests"]["cross_validated"]["global"])

    def test_paired_residual_tests_detect_lower_observed_error(self) -> None:
        result = paired_residual_tests(
            [.01] * 12, [.5] * 12, seed=123, randomization_iterations=999
        )
        self.assertLess(result["wilcoxon"], .05)
        self.assertLess(result["sign_test"], .05)
        self.assertLess(result["randomization_t"], .05)

    def test_local_worker_recommendation_reserves_cpu_and_obeys_memory(self) -> None:
        abundant = SystemResources(12, 16_000, 12_000, ())
        self.assertEqual(
            recommended_workers(abundant, reserved_cpus=3, samples=23, variables=1000),
            9,
        )
        constrained = SystemResources(12, 16_000, 2_000, ())
        self.assertLessEqual(
            recommended_workers(constrained, reserved_cpus=3, samples=23, variables=20_000),
            2,
        )


class SpectralCsvTests(unittest.TestCase):
    def test_inspects_variables_by_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spectrum.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerows(
                    [
                        ["", "sample-a", "sample-b"],
                        [0.1, 1.0, 2.0],
                        [0.2, 1.5, 2.5],
                        [0.3, 2.0, 3.0],
                    ]
                )

            result = inspect_spectral_csv(path)

        self.assertEqual(result.samples, 2)
        self.assertEqual(result.spectral_points, 3)
        self.assertTrue(result.axis_monotonic)
        self.assertEqual(result.sample_names, ("sample-a", "sample-b"))

    def test_rejects_ragged_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text(",a,b\n0.1,1,2\n0.2,3\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "columnas"):
                inspect_spectral_csv(path)

    def test_generic_matrix_supports_sample_rows_and_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proteomics.tsv"
            path.write_text(
                "sample_id\tP001\tP002\tP003\n"
                "sample-a\t1.0\t2.0\t3.0\n"
                "sample-b\t1.5\t2.5\t3.5\n"
                "sample-c\t2.0\t3.0\t4.0\n",
                encoding="utf-8",
            )
            summary = inspect_omics_matrix(
                path, orientation="samples_by_variables",
                representation="feature_table", modality="Proteómica",
            )
            restored = OmicsMatrixSummary.from_dict(summary.to_dict())
        self.assertEqual(summary.delimiter, "\t")
        self.assertEqual(summary.samples, 3)
        self.assertEqual(summary.features, 3)
        self.assertEqual(summary.sample_names, ("sample-a", "sample-b", "sample-c"))
        self.assertFalse(summary.feature_axis_numeric)
        self.assertEqual(restored, summary)

    def test_generic_matrix_reports_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.csv"
            path.write_text(
                "sample_id,gene-a,gene-b\ns1,1,\ns2,2,3\n",
                encoding="utf-8",
            )
            summary = inspect_omics_matrix(path, orientation="samples_by_variables")
        self.assertEqual(summary.missing_values, 1)


class AnalysisSpecTests(unittest.TestCase):
    def test_default_spec_is_valid(self) -> None:
        spec = AnalysisSpec.for_spectral_csv("data.csv")
        self.assertEqual(spec.to_dict()["preprocessing"]["scaling"], "pareto")

    def test_invalid_train_fraction_is_rejected(self) -> None:
        spec = AnalysisSpec(
            dataset=DatasetSpec("data.csv"),
            validation=ValidationSpec(train_fraction=1.0),
        )
        with self.assertRaisesRegex(ValueError, "train_fraction"):
            spec.validate()

    def test_random_subsets_requires_at_least_two_splits(self) -> None:
        spec = AnalysisSpec(
            dataset=DatasetSpec("data.csv"),
            validation=ValidationSpec(data_splits=1),
        )
        with self.assertRaisesRegex(ValueError, "data_splits"):
            spec.validate()

    def test_class_style_round_trip(self) -> None:
        style = ClassStyle(color="#abcdef", symbol="t", size=14)
        self.assertEqual(ClassStyle.from_dict(style.to_dict()), style)


class LoadingValueTests(unittest.TestCase):
    def test_pareto_backscaling_matches_reference_matlab_formula(self) -> None:
        loadings = np.asarray([[1.0, -2.0], [3.0, 4.0]])
        selected, values = backscaled_loading_values(
            loadings, [4.0, 9.0], 0, scaling="pareto"
        )
        np.testing.assert_allclose(selected, [1.0, 3.0])
        np.testing.assert_allclose(values, [2.0, 9.0])

    def test_loading_backscaling_rejects_incompatible_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "no coincide"):
            backscaled_loading_values([[1.0], [2.0]], [1.0], 0)


@unittest.skipUnless(
    _r_runtime_available(),
    "Los tests de workers requieren R y el runtime científico de Arii",
)
class PcaWorkerTests(unittest.TestCase):
    def test_mixomics_worker_returns_scores_and_loadings(self) -> None:
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            dataset = directory_path / "small.csv"
            with dataset.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["ppm", "a", "b", "c", "d", "e", "f", "g"])
                for point in range(8):
                    writer.writerow(
                        [point / 10, *[point + sample + (point * sample / 10) for sample in range(7)]]
                    )
            job = directory_path / "job.json"
            result = directory_path / "result.json"
            job.write_text(
                json.dumps(
                    {
                        "dataset": {"path": str(dataset)},
                        "selected_sample_indices": [0, 1, 2, 3, 4, 5, 6],
                        "classes": ["A", "A", "A", "B", "B", "B", "B"],
                        "preprocessing": {"scaling": "pareto"},
                        "n_components": 3,
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [str(find_rscript()), str(root / "r" / "pca_worker.R"), str(job), str(result)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(payload["dimensions"]["samples"], 7)
        self.assertEqual(len(payload["scores"]), 7)
        self.assertEqual(len(payload["loadings"]), 8)
        self.assertEqual(len(payload["explained_variance"]), 3)
        self.assertEqual(payload["preprocessing"]["scaling"], "pareto")
        self.assertTrue(payload["preprocessing"]["mean_center"])
        self.assertGreater(payload["hotelling_t2"]["limits"]["0.99"], payload["hotelling_t2"]["limits"]["0.95"])
        self.assertEqual(len(payload["fit_metrics"]["rmse"]), 3)
        self.assertAlmostEqual(payload["fit_metrics"]["r2x"][-1], payload["cumulative_variance"][-1])

    def test_workers_accept_generic_feature_tables_with_sample_rows(self) -> None:
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            dataset = directory_path / "features.tsv"
            names = [f"sample-{index}" for index in range(8)]
            with dataset.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream, delimiter="\t")
                writer.writerow(["sample_id", *[f"protein-{index}" for index in range(8)]])
                for sample_index, name in enumerate(names):
                    group_shift = 1.0 if sample_index >= 4 else -1.0
                    writer.writerow([
                        name,
                        *[
                            group_shift * (feature + 1)
                            + math.sin((sample_index + 1) * (feature + 2)) * 0.1
                            for feature in range(8)
                        ],
                    ])
            base_job = {
                "dataset": {
                    "path": str(dataset), "delimiter": "\t",
                    "orientation": "samples_by_variables",
                    "representation": "feature_table", "modality": "Proteómica",
                    "axis_label": "Característica",
                },
                "selected_sample_indices": list(range(8)),
                "classes": ["A"] * 4 + ["B"] * 4,
                "biological_ids": [f"id-{index}" for index in range(8)],
                "preprocessing": {"scaling": "pareto"},
                "n_components": 2,
                "validation": {
                    "strategy": "random_subsets", "repeats": 1,
                    "data_splits": 2, "train_fraction": 0.8, "seed": 9,
                },
            }
            job = directory_path / "generic.job.json"
            job.write_text(json.dumps(base_job), encoding="utf-8")
            for worker_name in ("pca_worker.R", "plsda_worker.R"):
                result = directory_path / f"{worker_name}.json"
                completed = subprocess.run(
                    [str(find_rscript()), str(root / "r" / worker_name),
                     str(job), str(result)],
                    capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                payload = json.loads(result.read_text(encoding="utf-8"))
                self.assertEqual(payload["sample_names"], names)
                self.assertEqual(payload["feature_ids"][0], "protein-0")
                self.assertEqual(payload["feature_axis"]["representation"], "feature_table")
                self.assertFalse(payload["feature_axis"]["numeric"])

    def test_plsda_worker_returns_external_performance(self) -> None:
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            dataset = directory_path / "classification.csv"
            with dataset.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                names = [f"a{i}" for i in range(4)] + [f"b{i}" for i in range(4)]
                writer.writerow(["ppm", *names])
                for point in range(12):
                    a_values = [
                        math.sin((point + 1) * (sample + 1)) * 0.15 + point * 0.03
                        for sample in range(4)
                    ]
                    b_values = [
                        math.cos((point + 1) * (sample + 2)) * 0.15
                        + point * 0.03
                        + (0.8 if point < 6 else -0.3)
                        for sample in range(4)
                    ]
                    writer.writerow([point / 10, *a_values, *b_values])
            job = directory_path / "job.json"
            result = directory_path / "result.json"
            job.write_text(
                json.dumps(
                    {
                        "dataset": {"path": str(dataset)},
                        "selected_sample_indices": list(range(8)),
                        "classes": ["A"] * 4 + ["B"] * 4,
                        "biological_ids": ["A1", "A1", "A2", "A2", "B1", "B1", "B2", "B2"],
                        "preprocessing": {"scaling": "pareto"},
                        "n_components": 2,
                        "validation": {"repeats": 2, "data_splits": 2, "seed": 42},
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [str(find_rscript()), str(root / "r" / "plsda_worker.R"), str(job), str(result)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(result.read_text(encoding="utf-8"))
            alternative_payloads = {}
            for strategy, validation, expected_submodels in (
                ("monte_carlo", {"repeats": 3, "data_splits": 2,
                                 "train_fraction": 0.8, "seed": 42}, 3),
                ("leave_one_out", {"repeats": 1, "data_splits": 2,
                                   "train_fraction": 0.8, "seed": 42}, 4),
                ("venetian_blinds", {"repeats": 1, "data_splits": 2,
                                     "train_fraction": 0.8, "seed": 42}, 2),
            ):
                alternative_job = json.loads(job.read_text(encoding="utf-8"))
                alternative_job["validation"] = {"strategy": strategy, **validation}
                job.write_text(json.dumps(alternative_job), encoding="utf-8")
                alternative_result = directory_path / f"{strategy}.result.json"
                completed = subprocess.run(
                    [str(find_rscript()), str(root / "r" / "plsda_worker.R"),
                     str(job), str(alternative_result)],
                    capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                alternative_payloads[strategy] = json.loads(
                    alternative_result.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    alternative_payloads[strategy]["performance"]["submodels"],
                    expected_submodels,
                )
                self.assertEqual(
                    alternative_payloads[strategy]["performance"]["validation_method"],
                    strategy,
                )
            job.write_text(json.dumps({
                **json.loads(job.read_text(encoding="utf-8")),
                "validation": {"repeats": 2, "data_splits": 2, "seed": 42},
            }), encoding="utf-8")
            orth_job = json.loads(job.read_text(encoding="utf-8"))
            orth_job["orthogonalize_plsda"] = True
            job.write_text(json.dumps(orth_job), encoding="utf-8")
            orth_result = directory_path / "orthogonalized_result.json"
            completed = subprocess.run(
                [str(find_rscript()), str(root / "r" / "plsda_worker.R"), str(job), str(orth_result)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            orth_payload = json.loads(orth_result.read_text(encoding="utf-8"))
        self.assertEqual(payload["method"], "plsda")
        self.assertEqual(payload["preprocessing"]["scaling"], "pareto")
        self.assertEqual(payload["class_levels"], ["A", "B"])
        self.assertEqual(payload["performance"]["repeats"], 2)
        self.assertEqual(payload["performance"]["data_splits"], 2)
        self.assertEqual(payload["performance"]["submodels"], 4)
        self.assertEqual(payload["performance"]["selection"]["criterion"], "one_standard_error_on_mean_ber")
        self.assertEqual(len(payload["candidate_models"]), 2)
        self.assertEqual(
            len(payload["component_names"]),
            payload["performance"]["selection"]["current_component"],
        )
        self.assertEqual(len(payload["performance"]["cv_auc_macro"]), 2)
        self.assertEqual(len(payload["performance"]["repetitions"]), 4)
        for fold in payload["performance"]["repetitions"]:
            train = set(fold["train_samples"])
            validation = set(fold["validation_samples"])
            for pair in ({"a0", "a1"}, {"a2", "a3"}, {"b0", "b1"}, {"b2", "b3"}):
                self.assertTrue(pair <= train or pair <= validation)
        self.assertEqual(len(payload["performance"]["confusion_matrices"]), 2)
        self.assertGreater(
            payload["hotelling_t2"]["limits"]["0.99"],
            payload["hotelling_t2"]["limits"]["0.95"],
        )
        self.assertEqual(len(payload["performance"]["r2y"]), 2)
        self.assertEqual(len(payload["performance"]["q2y"]), 2)
        self.assertEqual(
            np.asarray(payload["performance"]["calibration"]["decision_values"]).shape,
            (8, 2, 2),
        )
        self.assertEqual(
            np.asarray(payload["performance"]["repetitions"][0]["decision_values"]).shape,
            (4, 2, 2),
        )
        self.assertEqual(orth_payload["method"], "orthogonalized_plsda")
        self.assertTrue(orth_payload["orthogonalization"]["predictions_unchanged"])
        self.assertEqual(len(orth_payload["candidate_models"]), 2)
        self.assertEqual(
            orth_payload["performance"]["selection"]["current_component"],
            orth_payload["performance"]["selection"]["suggested_component"],
        )
        self.assertEqual(
            len(orth_payload["component_names"]),
            orth_payload["performance"]["selection"]["current_component"],
        )
        np.testing.assert_allclose(
            orth_payload["performance"]["calibration"]["decision_values"],
            payload["performance"]["calibration"]["decision_values"],
        )
        orth_decisions = np.asarray(
            orth_payload["performance"]["calibration"]["decision_values"], dtype=float
        )
        for candidate_index, candidate in enumerate(orth_payload["candidate_models"]):
            orth_scores = np.asarray(candidate["scores"], dtype=float)
            cross_products = orth_scores.T @ orth_scores
            np.testing.assert_allclose(
                cross_products - np.diag(np.diag(cross_products)), 0, atol=1e-8
            )
            self.assertAlmostEqual(
                abs(
                    np.corrcoef(
                        orth_scores[:, 0], orth_decisions[:, 1, candidate_index]
                    )[0, 1]
                ),
                1.0,
                places=10,
            )
    def test_permutation_worker_returns_empirical_p_values(self) -> None:
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            dataset = directory_path / "permutation.csv"
            names = [f"a{i}" for i in range(6)] + [f"b{i}" for i in range(6)]
            with dataset.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["ppm", *names])
                for variable in range(10):
                    values = [
                        (-1 if sample < 6 else 1) * (1.0 + variable * 0.04)
                        + math.sin((sample + 1) * (variable + 2)) * 0.08
                        for sample in range(12)
                    ]
                    writer.writerow([variable / 10, *values])
            job = directory_path / "job.json"
            result = directory_path / "result.json"
            job.write_text(
                json.dumps(
                    {
                        "method": "plsda",
                        "dataset": {"path": str(dataset)},
                        "preprocessing": {"scaling": "pareto"},
                        "selected_sample_indices": list(range(12)),
                        "classes": ["A"] * 6 + ["B"] * 6,
                        "biological_ids": [f"id{i}" for i in range(12)],
                        "current_components": 2,
                        "current_orthogonal_components": 0,
                        "orthogonal_selection": "manual",
                        "validation": {"repeats": 1, "data_splits": 2},
                        "permutations": {"count": 3, "seed": 123},
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    str(find_rscript()), str(root / "r" / "permutation_worker.R"),
                    str(job), str(result),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(result.read_text(encoding="utf-8"))
            for strategy, validation in (
                ("monte_carlo", {"repeats": 2, "data_splits": 2,
                                 "train_fraction": 0.8, "seed": 7}),
                ("leave_one_out", {"repeats": 1, "data_splits": 2,
                                   "train_fraction": 0.8, "seed": 7}),
                ("venetian_blinds", {"repeats": 1, "data_splits": 3,
                                     "train_fraction": 0.8, "seed": 7}),
            ):
                alternative_job = json.loads(job.read_text(encoding="utf-8"))
                alternative_job["validation"] = {"strategy": strategy, **validation}
                alternative_job["permutations"]["count"] = 1
                job.write_text(json.dumps(alternative_job), encoding="utf-8")
                alternative_result = directory_path / f"permutation-{strategy}.json"
                completed = subprocess.run(
                    [str(find_rscript()), str(root / "r" / "permutation_worker.R"),
                     str(job), str(alternative_result)],
                    capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                alternative_payload = json.loads(
                    alternative_result.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    alternative_payload["validation"]["validation_method"], strategy
                )
        self.assertEqual(payload["permutations"], 3)
        self.assertEqual(payload["selection_policy"], "fixed_current_complexity")
        self.assertEqual(len(payload["null"]["q2y"]), 3)
        self.assertEqual(len(payload["correlation_to_original"]), 3)
        self.assertTrue(all(-1 <= value <= 1 for value in payload["correlation_to_original"]))
        self.assertGreaterEqual(payload["timing"]["total_seconds"], 0)
        self.assertEqual(len(payload["timing"]["permutation_seconds"]), 3)
        self.assertEqual(payload["exchangeability_unit"], "biological_id_or_sample")
        residual = payload["residual_comparison"]
        self.assertEqual(residual["class_levels"], ["A", "B"])
        self.assertEqual(
            len(residual["null_standardized_ssq"]["cross_validated"]["global"]), 3
        )
        for value in residual["tests"]["cross_validated"]["global"].values():
            if isinstance(value, (int, float)) and "error" not in str(value):
                self.assertTrue(math.isfinite(value))
        python_tests = build_residual_tests(
            residual["observed_error_by_sample"],
            residual["null_error_sum_by_sample"],
            payload["permutations"], residual["class_levels"],
            seed=payload["seed"] + 700001,
        )
        for test_name in ("wilcoxon", "sign_test", "randomization_t"):
            self.assertAlmostEqual(
                residual["tests"]["cross_validated"]["global"][test_name],
                python_tests["cross_validated"]["global"][test_name], places=10,
            )
        for value in payload["empirical_p"].values():
            self.assertGreaterEqual(value, 0.25)
            self.assertLessEqual(value, 1.0)


class ClassificationMetricTests(unittest.TestCase):
    def test_binary_roc_is_perfect_for_separated_scores(self) -> None:
        curve = binary_roc([False, False, True, True], [0.1, 0.2, 0.8, 0.9])
        self.assertAlmostEqual(curve.auc, 1.0)
        self.assertEqual(curve.false_positive_rate[0], 0.0)
        self.assertEqual(curve.true_positive_rate[-1], 1.0)

    def test_external_scores_are_averaged_by_sample(self) -> None:
        repetitions = [
            {
                "validation_samples": ["a", "b"],
                "truth": ["A", "B"],
                "decision_values": [[[0.8], [0.2]], [[0.3], [0.7]]],
            },
            {
                "validation_samples": ["a", "b"],
                "truth": ["A", "B"],
                "decision_values": [[[1.0], [0.0]], [[0.1], [0.9]]],
            },
        ]
        names, truths, scores = mean_external_scores(repetitions, 0)
        self.assertEqual(names, ["a", "b"])
        self.assertEqual(truths, ["A", "B"])
        np.testing.assert_allclose(scores, [[0.9, 0.1], [0.2, 0.8]])

    def test_threshold_curve_finds_separating_cutoff(self) -> None:
        curve = sensitivity_specificity_curve(
            [False, False, True, True], [0.1, 0.2, 0.8, 0.9]
        )
        self.assertGreater(curve.optimal_threshold, 0.2)
        self.assertLessEqual(curve.optimal_threshold, 0.8)
        self.assertEqual(curve.sensitivity[curve.optimal_index], 1.0)
        self.assertEqual(curve.specificity[curve.optimal_index], 1.0)


class ProjectFileTests(unittest.TestCase):
    def test_project_round_trip_with_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "data.csv"
            dataset.write_text("ppm,a\n0.1,1\n", encoding="utf-8")
            payload = {
                "schema_version": "1.0",
                "dataset": {"path": str(dataset), "sha256": fingerprint_file(dataset)},
                "samples": [{"name": "a", "included": True, "class": "Control"}],
            }
            result = {"method": "pca", "scores": [[1.0, 2.0]]}
            project = save_project(root / "example", payload, result)
            restored, restored_result = load_project(project)
        self.assertEqual(project.suffix, ".arii")
        self.assertEqual(restored["samples"][0]["class"], "Control")
        self.assertEqual(restored_result, result)


class MetadataTests(unittest.TestCase):
    def test_export_and_import_matches_by_sample_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.csv"
            export_metadata_template(
                path,
                ["sample-b", "sample-a"],
                {
                    "sample-a": {"class": "Control", "batch": "L1"},
                    "sample-b": {"class": "Tratado", "batch": "L2"},
                },
            )
            result = import_metadata(path, ["sample-a", "sample-b", "sample-c"])
        self.assertEqual(result.values["sample-a"]["class"], "Control")
        self.assertEqual(result.values["sample-b"]["batch"], "L2")
        self.assertEqual(result.matched_samples, ("sample-a", "sample-b"))
        self.assertEqual(result.missing_samples, ("sample-c",))

    def test_import_accepts_spanish_headers_and_reports_unknown_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.tsv"
            path.write_text(
                "muestra\tclase\ttratamiento\tlote\tindividuo\treplica\n"
                "known\tA\tT1\tL1\tI1\tR1\n"
                "unknown\tB\tT2\tL2\tI2\tR1\n",
                encoding="utf-8",
            )
            result = import_metadata(path, ["known"])
        self.assertEqual(result.values["known"]["biological_id"], "I1")
        self.assertEqual(result.unknown_samples, ("unknown",))


class ExportResultsTests(unittest.TestCase):
    def test_exports_reproducible_pca_tables(self) -> None:
        result = {
            "component_names": ["PC1", "PC2"],
            "sample_names": ["a", "b"],
            "classes": ["A", "B"],
            "scores": [[1.0, 2.0], [3.0, 4.0]],
            "ppm": [0.1, 0.2],
            "standard_deviations": [0.5, 0.6],
            "loadings": [[0.7, 0.8], [0.9, 1.0]],
            "explained_variance": [0.6, 0.3],
            "cumulative_variance": [0.6, 0.9],
            "dimensions": {"samples": 2, "variables": 2, "removed_constant_variables": 0},
            "engine": {"name": "mixOmics", "version": "test", "r_version": "R test"},
            "fit_metrics": {
                "components": [1, 2],
                "rmse": [1.0, 0.8],
                "r2x": [0.6, 0.9],
                "scope": "full_model_reconstruction",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            files = export_numeric_results(
                directory,
                result,
                {"a": {"class": "A", "batch": "L1"}},
                {"schema_version": "1.0"},
            )
            scores = (Path(directory) / "pca_scores.csv").read_text(encoding="utf-8-sig")
            report = (Path(directory) / "pca_report.md").read_text(encoding="utf-8")
            fit = (Path(directory) / "pca_fit.csv").read_text(encoding="utf-8-sig")
        self.assertEqual(len(files), 6)
        self.assertIn("sample_name,class,treatment,batch,biological_id,replicate,PC1,PC2", scores)
        self.assertIn("a,A,,L1,,,1.0,2.0", scores)
        self.assertIn("Motor: mixOmics test", report)
        self.assertIn("rmse_reconstruction", fit)
        self.assertIn("Ajuste del modelo completo", report)

    def test_exports_plsda_performance_and_external_predictions(self) -> None:
        result = {
            "method": "plsda",
            "component_names": ["LV1", "LV2"],
            "sample_names": ["a", "b"],
            "classes": ["A", "B"],
            "class_levels": ["A", "B"],
            "scores": [[1, 2], [-1, -2]],
            "ppm": [0.1, 0.2],
            "standard_deviations": [1, 1],
            "loadings": [[0.2, 0.3], [0.4, 0.5]],
            "dimensions": {"samples": 2, "variables": 2},
            "engine": {"name": "mixOmics", "version": "test"},
            "permutation_test": {
                "permutations": 2,
                "selection_policy": "fixed_current_complexity",
                "exchangeability_unit": "sample",
                "observed": {"r2y": 0.8, "q2y": 0.6, "ber": 0.1, "auc_macro": 0.9},
                "null": {
                    "r2y": [0.1, 0.2], "q2y": [-0.2, 0.0],
                    "ber": [0.5, 0.4], "auc_macro": [0.5, 0.6],
                },
                "empirical_p": {"r2y": 1 / 3, "q2y": 1 / 3, "ber": 1 / 3, "auc_macro": 1 / 3},
                "null_rejected_fraction": [0, 0],
                "correlation_to_original": [-0.5, 0.1],
                "timing": {"permutation_seconds": [1.2, 1.3]},
            },
            "performance": {
                "distance": "max.dist", "repeats": 1, "train_fraction": 0.8,
                "mean_ber": [0.2, 0.1], "sd_ber": [None, None],
                "mean_accuracy": [0.8, 0.9], "sd_accuracy": [None, None],
                "r2y": [0.5, 0.8], "q2y": [0.3, 0.6],
                "components": [1, 2],
                "selection": {"suggested_component": 2, "current_component": 2},
                "calibration": {
                    "truth": ["A", "B"],
                    "decision_values": [[[0.9, 0.8], [0.1, 0.2]], [[0.2, 0.1], [0.8, 0.9]]],
                },
                "confusion_matrices": [
                    {"component": 1, "labels": ["A", "B"], "matrix": [[1, 0], [0, 1]]},
                    {"component": 2, "labels": ["A", "B"], "matrix": [[1, 0], [0, 1]]},
                ],
                "repetitions": [{
                    "repeat": 1, "validation_samples": ["a", "b"], "truth": ["A", "B"],
                    "predicted": [["A", "A"], ["B", "B"]],
                    "decision_values": [[[0.9, 0.8], [0.1, 0.2]], [[0.2, 0.1], [0.8, 0.9]]],
                }],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            files = export_plsda_results(directory, result, {}, {"schema_version": "1.0"})
            performance = (Path(directory) / "plsda_performance.csv").read_text(encoding="utf-8-sig")
            predictions = (Path(directory) / "plsda_external_predictions.csv").read_text(encoding="utf-8-sig")
            roc = (Path(directory) / "plsda_roc_curves.csv").read_text(encoding="utf-8-sig")
            thresholds = (Path(directory) / "plsda_threshold_curves.csv").read_text(encoding="utf-8-sig")
            permutations = (Path(directory) / "plsda_permutation_test.csv").read_text(encoding="utf-8-sig")
        self.assertEqual(len(files), 11)
        self.assertIn("r2y,q2y", performance)
        self.assertIn("decision_A_modelo_2_lv", predictions)
        self.assertIn("cross_validation,2 LVs,A", roc)
        self.assertIn("full_model_fit,2 LVs,A", roc)
        self.assertIn("maximum_youden_then_balance", thresholds)
        self.assertIn(
            "permutation,correlation_y,r2y,q2y,ber,auc_macro,rejected_fraction,elapsed_seconds",
            permutations,
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from arii.metrics import binary_roc, mean_external_scores, sensitivity_specificity_curve


def export_numeric_results(
    directory: str | Path,
    result: dict,
    sample_metadata: dict[str, dict[str, str]],
    analysis_manifest: dict,
) -> list[Path]:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    scores_path = destination / "pca_scores.csv"
    component_names = result["component_names"]
    metadata_fields = ("class", "treatment", "batch", "biological_id", "replicate")
    with scores_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_name", *metadata_fields, *component_names])
        for sample_name, result_class, scores in zip(
            result["sample_names"], result["classes"], result["scores"], strict=True
        ):
            metadata = sample_metadata.get(sample_name, {})
            writer.writerow(
                [
                    sample_name,
                    metadata.get("class", result_class),
                    *(metadata.get(field, "") for field in metadata_fields[1:]),
                    *scores,
                ]
            )
    written.append(scores_path)

    loadings_path = destination / "pca_loadings.csv"
    with loadings_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        feature_ids = result.get("feature_ids")
        if feature_ids:
            writer.writerow([
                "feature_id", "axis_value", "standard_deviation", *component_names
            ])
            for feature_id, axis_value, deviation, loadings in zip(
                feature_ids, result["ppm"], result["standard_deviations"],
                result["loadings"], strict=True,
            ):
                writer.writerow([feature_id, axis_value, deviation, *loadings])
        else:
            writer.writerow(["ppm", "standard_deviation", *component_names])
            for ppm, deviation, loadings in zip(
                result["ppm"], result["standard_deviations"],
                result["loadings"], strict=True,
            ):
                writer.writerow([ppm, deviation, *loadings])
    written.append(loadings_path)

    variance_path = destination / "pca_variance.csv"
    with variance_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["component", "explained_fraction", "explained_percent", "cumulative_fraction", "cumulative_percent"])
        for name, explained, cumulative in zip(
            component_names,
            result["explained_variance"],
            result["cumulative_variance"],
            strict=True,
        ):
            writer.writerow([name, explained, explained * 100, cumulative, cumulative * 100])
    written.append(variance_path)

    fit_metrics = result.get("fit_metrics")
    if fit_metrics:
        fit_path = destination / "pca_fit.csv"
        with fit_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["component", "rmse_reconstruction", "r2x_cumulative"])
            for values in zip(
                fit_metrics["components"],
                fit_metrics["rmse"],
                fit_metrics["r2x"],
                strict=True,
            ):
                writer.writerow(values)
        written.append(fit_path)

    validation = result.get("validation")
    if validation:
        validation_path = destination / "pca_validation.csv"
        with validation_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["component", "mean_rmse", "sd_rmse", "mean_q2x", "sd_q2x"])
            for values in zip(
                validation["components"],
                validation["mean_rmse"],
                validation["sd_rmse"],
                validation["mean_q2x"],
                validation["sd_q2x"],
                strict=True,
            ):
                writer.writerow(values)
        written.append(validation_path)

        repetitions_path = destination / "pca_validation_repetitions.csv"
        with repetitions_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            metric_columns = [f"rmse_PC{i}" for i in validation["components"]]
            metric_columns += [f"q2x_PC{i}" for i in validation["components"]]
            writer.writerow(["repeat", "train_samples", "validation_samples", *metric_columns])
            for repetition in validation["repetitions"]:
                writer.writerow(
                    [
                        repetition["repeat"],
                        ";".join(repetition["train_samples"]),
                        ";".join(repetition["validation_samples"]),
                        *repetition["rmse"],
                        *repetition["q2x"],
                    ]
                )
        written.append(repetitions_path)

    manifest_path = destination / "analysis_manifest.json"
    manifest_path.write_text(
        json.dumps(analysis_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written.append(manifest_path)

    report_path = destination / "pca_report.md"
    scaling = result.get("preprocessing", {}).get("scaling", "pareto")
    dimensions = result["dimensions"]
    engine = result["engine"]
    variance_rows = "\n".join(
        f"| {name} | {explained * 100:.4f} | {cumulative * 100:.4f} |"
        for name, explained, cumulative in zip(
            component_names,
            result["explained_variance"],
            result["cumulative_variance"],
            strict=True,
        )
    )
    report_path.write_text(
        "# Informe PCA\n\n"
        f"- Motor: {engine['name']} {engine['version']}\n"
        f"- R: {engine['r_version']}\n"
        f"- Muestras modeladas: {dimensions['samples']}\n"
        f"- Variables modeladas: {dimensions['variables']}\n"
        f"- Variables constantes retiradas: {dimensions['removed_constant_variables']}\n"
        f"- Preprocesamiento: centrado; escalado {scaling}\n\n"
        "## Varianza explicada\n\n"
        "| Componente | Explicada (%) | Acumulada (%) |\n"
        "|---|---:|---:|\n"
        f"{variance_rows}\n\n"
        "## Archivos\n\n"
        "- `pca_scores.csv`: scores y metadatos por muestra.\n"
        "- `pca_loadings.csv`: identificador/eje, desviación estándar y loadings.\n"
        "- `pca_variance.csv`: varianza explicada y acumulada.\n"
        "- `pca_fit.csv`: RMSE de reconstrucción y R²X acumulado.\n"
        "- `analysis_manifest.json`: configuración reproducible.\n"
        "- Figuras PNG/SVG: estado visual seleccionado al exportar.\n",
        encoding="utf-8",
    )
    if fit_metrics:
        with report_path.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n## Ajuste del modelo completo\n\n"
                f"- RMSE final: {fit_metrics['rmse'][-1]:.8g}\n"
                f"- R²X acumulado final: {fit_metrics['r2x'][-1]:.8g}\n"
                "- Estas métricas describen reconstrucción del modelo ajustado; no son validación externa.\n"
            )
    if validation:
        with report_path.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n## Validación repetida\n\n"
                f"- Estrategia: {validation['strategy']}\n"
                f"- Repeticiones: {validation['repeats']}\n"
                f"- Fracción de entrenamiento: {validation['train_fraction']:.2f}\n"
                f"- Semilla: {validation['seed']}\n"
                "- Preprocesamiento: estimado únicamente con entrenamiento.\n"
                "- `pca_validation.csv`: resumen por componente.\n"
                "- `pca_validation_repetitions.csv`: métricas y particiones completas.\n"
            )
    written.append(report_path)
    return written


def export_plsda_results(
    directory: str | Path,
    result: dict,
    sample_metadata: dict[str, dict[str, str]],
    analysis_manifest: dict,
) -> list[Path]:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    components = result["component_names"]
    performance = result["performance"]
    selection = performance.get("selection", {})
    current_component = int(
        selection.get("current_component", selection.get("suggested_component", len(components)))
    )
    current_index = current_component - 1
    model_components = np.atleast_1d(
        performance.get("components", list(range(1, len(components) + 1)))
    ).astype(int)
    model_labels = [f"{value} LV" + ("s" if value != 1 else "") for value in model_components]

    def selected_metric(key: str) -> object:
        values = performance.get(key)
        if values is None or current_index >= len(np.atleast_1d(values)):
            return "NA"
        return np.atleast_1d(values)[current_index]

    scores_path = destination / "plsda_scores.csv"
    with scores_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_name", "class", "treatment", "batch", "biological_id", "replicate", *components])
        for sample_name, result_class, scores in zip(
            result["sample_names"], result["classes"], result["scores"], strict=True
        ):
            metadata = sample_metadata.get(sample_name, {})
            writer.writerow([
                sample_name,
                metadata.get("class", result_class),
                metadata.get("treatment", ""),
                metadata.get("batch", ""),
                metadata.get("biological_id", ""),
                metadata.get("replicate", ""),
                *scores,
            ])
    written.append(scores_path)

    loadings_path = destination / "plsda_loadings.csv"
    with loadings_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        feature_ids = result.get("feature_ids")
        if feature_ids:
            writer.writerow([
                "feature_id", "axis_value", "standard_deviation", *components
            ])
            for feature_id, axis_value, deviation, loadings in zip(
                feature_ids, result["ppm"], result["standard_deviations"],
                result["loadings"], strict=True,
            ):
                writer.writerow([feature_id, axis_value, deviation, *loadings])
        else:
            writer.writerow(["ppm", "standard_deviation", *components])
            for ppm, deviation, loadings in zip(
                result["ppm"], result["standard_deviations"],
                result["loadings"], strict=True,
            ):
                writer.writerow([ppm, deviation, *loadings])
    written.append(loadings_path)

    missing_metrics = [None] * len(model_components)
    performance_path = destination / "plsda_performance.csv"
    with performance_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "component", "mean_ber", "sd_ber", "se_ber", "mean_accuracy",
            "sd_accuracy", "calibration_ber", "calibration_accuracy",
            "calibration_correct", "r2x", "r2y", "q2y", "cv_auc_macro",
            "calibration_auc_macro",
        ])
        for values in zip(
            model_labels,
            performance["mean_ber"], performance["sd_ber"],
            performance.get("se_ber", missing_metrics),
            performance["mean_accuracy"], performance["sd_accuracy"],
            performance.get("calibration_ber", missing_metrics),
            performance.get("calibration_accuracy", missing_metrics),
            performance.get("calibration_correct", missing_metrics),
            performance.get("r2x", missing_metrics),
            performance.get("r2y", missing_metrics),
            performance.get("q2y", missing_metrics),
            performance.get("cv_auc_macro", missing_metrics),
            performance.get("calibration_auc_macro", missing_metrics), strict=True,
        ):
            writer.writerow(values)
    written.append(performance_path)

    for confusion in performance["confusion_matrices"]:
        if int(confusion["component"]) != current_component:
            continue
        component_name = model_labels[current_index]
        confusion_path = destination / f"plsda_confusion_modelo_{current_component}_lv.csv"
        with confusion_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["truth/predicted", *confusion["labels"]])
            for label, values in zip(confusion["labels"], confusion["matrix"], strict=True):
                writer.writerow([label, *values])
        written.append(confusion_path)

    predictions_path = destination / "plsda_external_predictions.csv"
    class_levels = result["class_levels"]
    predicted_columns = [f"predicted_modelo_{current_component}_lv"]
    decision_columns = [
        f"decision_{class_name}_modelo_{current_component}_lv"
        for class_name in class_levels
    ]
    with predictions_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["iteration", "split", "sample_name", "truth", *predicted_columns, *decision_columns])
        for repetition in performance["repetitions"]:
            for row, sample_name in enumerate(repetition["validation_samples"]):
                decisions = repetition["decision_values"][row]
                flattened = [
                    decisions[class_index][current_index]
                    for class_index in range(len(class_levels))
                ]
                writer.writerow([
                    repetition["repeat"], repetition.get("split", 1),
                    sample_name, repetition["truth"][row],
                    repetition["predicted"][row][current_index], *flattened,
                ])
    written.append(predictions_path)

    roc_path = destination / "plsda_roc_curves.csv"
    with roc_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["source", "component", "class", "false_positive_rate", "true_positive_rate", "auc"])
        calibration = performance.get("calibration")
        for component_index, component_name in [(current_index, model_labels[current_index])]:
            _, cv_truths, cv_scores = mean_external_scores(
                performance["repetitions"], component_index
            )
            sources: list[tuple[str, list[str], np.ndarray]] = [
                ("cross_validation", cv_truths, cv_scores)
            ]
            if calibration:
                calibration_values = np.asarray(calibration["decision_values"], dtype=float)
                sources.append(
                    (
                        "full_model_fit",
                        list(calibration["truth"]),
                        calibration_values[:, :, component_index],
                    )
                )
            for source, truths, scores in sources:
                for class_index, class_name in enumerate(class_levels):
                    curve = binary_roc(
                        np.asarray(truths) == class_name, scores[:, class_index]
                    )
                    for false_positive_rate, true_positive_rate in zip(
                        curve.false_positive_rate, curve.true_positive_rate, strict=True
                    ):
                        writer.writerow(
                            [
                                source,
                                component_name,
                                class_name,
                                false_positive_rate,
                                true_positive_rate,
                                curve.auc,
                            ]
                        )
    written.append(roc_path)

    threshold_path = destination / "plsda_threshold_curves.csv"
    with threshold_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "source", "component", "class", "threshold", "sensitivity",
            "specificity", "optimal_threshold", "selection_rule",
        ])
        calibration = performance.get("calibration")
        for component_index, component_name in [(current_index, model_labels[current_index])]:
            _, cv_truths, cv_scores = mean_external_scores(
                performance["repetitions"], component_index
            )
            sources: list[tuple[str, list[str], np.ndarray]] = [
                ("cross_validation", cv_truths, cv_scores)
            ]
            if calibration:
                calibration_values = np.asarray(calibration["decision_values"], dtype=float)
                sources.append(
                    ("full_model_fit", list(calibration["truth"]), calibration_values[:, :, component_index])
                )
            for source, truths, scores in sources:
                for class_index, class_name in enumerate(class_levels):
                    curve = sensitivity_specificity_curve(
                        np.asarray(truths) == class_name, scores[:, class_index]
                    )
                    for threshold, sensitivity, specificity in zip(
                        curve.thresholds, curve.sensitivity, curve.specificity, strict=True
                    ):
                        writer.writerow([
                            source, component_name, class_name, threshold,
                            sensitivity, specificity, curve.optimal_threshold,
                            "maximum_youden_then_balance",
                        ])
    written.append(threshold_path)

    permutation = result.get("permutation_test")
    if permutation:
        permutation_path = destination / "plsda_permutation_test.csv"
        null_metrics = permutation["null"]
        permutation_count = int(permutation["permutations"])
        rejected = np.atleast_1d(
            permutation.get("null_rejected_fraction", [0] * permutation_count)
        )
        correlations = np.atleast_1d(
            permutation.get("correlation_to_original", [None] * permutation_count)
        )
        elapsed = np.atleast_1d(
            permutation.get("timing", {}).get(
                "permutation_seconds", [None] * permutation_count
            )
        )
        with permutation_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                ["permutation", "correlation_y", "r2y", "q2y", "ber", "auc_macro",
                 "rejected_fraction", "elapsed_seconds"]
            )
            for index in range(permutation_count):
                writer.writerow(
                    [
                        index + 1,
                        correlations[index],
                        np.atleast_1d(null_metrics["r2y"])[index],
                        np.atleast_1d(null_metrics["q2y"])[index],
                        np.atleast_1d(null_metrics["ber"])[index],
                        np.atleast_1d(null_metrics["auc_macro"])[index],
                        rejected[index],
                        elapsed[index],
                    ]
                )
        written.append(permutation_path)
        residual = permutation.get("residual_comparison")
        if residual:
            residual_values_path = destination / "plsda_permutation_residual_ssq.csv"
            scopes = ["global", *residual["class_levels"]]
            with residual_values_path.open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.writer(stream)
                writer.writerow([
                    "permutation", "correlation_y", "response",
                    "calibration_standardized_ssq", "cv_standardized_ssq",
                ])
                for index in range(permutation_count):
                    for scope in scopes:
                        writer.writerow([
                            index + 1, correlations[index], scope,
                            np.atleast_1d(
                                residual["null_standardized_ssq"]["calibration"][scope]
                            )[index],
                            np.atleast_1d(
                                residual["null_standardized_ssq"]["cross_validated"][scope]
                            )[index],
                        ])
            written.append(residual_values_path)

            residual_tests_path = destination / "plsda_permutation_residual_tests.csv"
            with residual_tests_path.open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.writer(stream)
                writer.writerow([
                    "phase", "response", "wilcoxon_p", "sign_test_p",
                    "randomization_t_p", "samples", "observed_mse",
                    "mean_permuted_mse", "mean_error_improvement",
                ])
                for phase in ("calibration", "cross_validated"):
                    for scope in scopes:
                        tests = residual["tests"][phase][scope]
                        writer.writerow([
                            phase, scope, tests["wilcoxon"], tests["sign_test"],
                            tests["randomization_t"], tests["samples"],
                            tests["observed_mean_squared_error"],
                            tests["permuted_mean_squared_error"],
                            tests["mean_error_improvement"],
                        ])
            written.append(residual_tests_path)
        permutation_json_path = destination / "plsda_permutation_test.json"
        permutation_json_path.write_text(
            json.dumps(permutation, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written.append(permutation_json_path)

    manifest_path = destination / "analysis_manifest.json"
    manifest_path.write_text(json.dumps(analysis_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(manifest_path)

    report_path = destination / "plsda_report.md"
    report_title = (
        "OPLS-DA" if result.get("method") == "orthogonalized_plsda" else "PLS-DA"
    )
    selection = performance.get("selection", {})
    effective = performance.get("effective_validation_fraction", {})
    validation_method = performance.get("validation_method", "random_subsets")
    validation_description = {
        "random_subsets": (
            "Random Subsets estratificado, "
            f"{performance.get('data_splits', 1)} data splits × "
            f"{performance['repeats']} iteraciones"
        ),
        "monte_carlo": (
            f"Monte Carlo estratificado, {performance['repeats']} particiones "
            "aleatorias independientes"
        ),
        "leave_one_out": (
            f"Leave-one-out por unidad biológica, "
            f"{performance.get('submodels', performance['repeats'])} submodelos"
        ),
        "venetian_blinds": (
            f"Venetian blinds por unidad biológica, "
            f"{performance.get('data_splits', 1)} bloques sistemáticos"
        ),
    }.get(validation_method, str(performance.get("strategy", validation_method)))
    report_text = (
        f"# Informe {report_title}\n\n"
        f"- Motor: {result['engine']['name']} {result['engine']['version']}\n"
        f"- Muestras: {result['dimensions']['samples']}\n"
        f"- Variables: {result['dimensions']['variables']}\n"
        f"- Clases: {', '.join(class_levels)}\n"
        f"- Validación: {validation_description} = "
        f"{performance.get('submodels', performance['repeats'])} submodelos\n"
        f"- Proporción por submodelo: {performance['train_fraction'] * 100:.0f}% entrenamiento / "
        f"{(1 - performance['train_fraction']) * 100:.0f}% validación\n"
        f"- Unidad de remuestreo: {performance.get('resampling_unit', 'sample')}\n"
        f"- Semilla: {performance.get('seed', 'NA')}\n"
        f"- Distancia: {performance['distance']}\n"
        f"- Modelo actual: {current_component} LV(s)\n"
        f"- BER del modelo actual: {performance['mean_ber'][current_index]:.6g}\n"
        f"- Exactitud del modelo actual: {performance['mean_accuracy'][current_index]:.6g}\n"
        f"- R²Y del modelo actual: {selected_metric('r2y')}\n"
        f"- Q²Y del modelo actual: {selected_metric('q2y')}\n\n"
        f"- AUC CV macro del modelo actual: {selected_metric('cv_auc_macro')}\n"
        f"- Componente de BER mínimo: {selection.get('minimum_error_component', 'NA')}\n"
        f"- Componente sugerido: {selection.get('suggested_component', 'NA')}\n"
        f"- Regla de selección: {selection.get('criterion', 'NA')}\n"
    )
    report_text += (
        f"- Validación efectiva: {effective['minimum'] * 100:.2f}–"
        f"{effective['maximum'] * 100:.2f}% (media {effective['average'] * 100:.2f}%)\n\n"
        if effective else "\n"
    )
    report_text += (
        "Las métricas de clasificación y Q²Y usan únicamente predicciones externas.\n"
        "La ROC exportada separa `full_model_fit` (ajuste) de `cross_validation`; "
        "esta última promedia las predicciones externas por muestra.\n"
    )
    if permutation:
        p_values = permutation["empirical_p"]
        report_text += (
            "\n## Test de permutaciones\n\n"
            f"- Permutaciones: {permutation['permutations']}\n"
            f"- Política de selección: {permutation['selection_policy']}\n"
            f"- Unidad de intercambio: {permutation['exchangeability_unit']}\n"
            f"- p empírico R²Y: {p_values['r2y']}\n"
            f"- p empírico Q²Y: {p_values['q2y']}\n"
            f"- p empírico BER: {p_values['ber']}\n"
            f"- p empírico AUC macro: {p_values['auc_macro']}\n"
            "- Corrección: (1 + casos nulos tan extremos) / (1 + permutaciones).\n"
        )
        residual = permutation.get("residual_comparison")
        if residual:
            calibration = residual["tests"]["calibration"]["global"]
            cross_validated = residual["tests"]["cross_validated"]["global"]
            report_text += (
                "\n### Comparación residual compatible conceptualmente con PLS_Toolbox\n\n"
                "Los contrastes son unilaterales: el error observado debe ser menor "
                "que el error medio bajo respuestas permutadas.\n\n"
                f"- Ajuste — Wilcoxon: {calibration['wilcoxon']}\n"
                f"- Ajuste — Sign Test: {calibration['sign_test']}\n"
                f"- Ajuste — Randomization t-test: {calibration['randomization_t']}\n"
                f"- CV — Wilcoxon: {cross_validated['wilcoxon']}\n"
                f"- CV — Sign Test: {cross_validated['sign_test']}\n"
                f"- CV — Randomization t-test: {cross_validated['randomization_t']}\n"
            )
    report_path.write_text(
        report_text,
        encoding="utf-8",
    )
    written.append(report_path)
    return written

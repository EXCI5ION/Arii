suppressPackageStartupMessages(library(jsonlite))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("Uso: permutation_worker.R <job.json> <result.json>")
job <- fromJSON(
  paste(readLines(args[[1]], warn = FALSE, encoding = "UTF-8"), collapse = "\n"),
  simplifyVector = TRUE
)

method <- as.character(job$method)
if (!method %in% c("plsda", "orthogonalized_plsda")) {
  stop("El test de permutaciones requiere PLS-DA u OPLS-DA")
}
suppressPackageStartupMessages(library(mixOmics))

delimiter <- if (is.null(job$dataset$delimiter)) "," else as.character(job$dataset$delimiter)
raw <- read.table(
  job$dataset$path, header = TRUE, sep = delimiter, check.names = FALSE,
  stringsAsFactors = FALSE, quote = "\"", comment.char = ""
)
orientation <- if (is.null(job$dataset$orientation)) {
  "variables_by_samples"
} else as.character(job$dataset$orientation)
if (orientation == "samples_by_variables") {
  sample_names_all <- as.character(raw[[1]])
  X_all <- as.matrix(raw[-1])
} else if (orientation == "variables_by_samples") {
  sample_names_all <- names(raw)[-1]
  X_all <- t(as.matrix(raw[-1]))
} else stop("Orientación de matriz no reconocida")
storage.mode(X_all) <- "double"
if (anyNA(X_all) || any(!is.finite(X_all))) {
  stop("La matriz contiene valores ausentes, infinitos o no numéricos")
}
selected <- as.integer(job$selected_sample_indices) + 1L
X <- X_all[selected, , drop = FALSE]
sample_names <- sample_names_all[selected]
classes <- as.character(job$classes[selected])
class_levels <- sort(unique(classes))
if (length(class_levels) < 2L) stop("Se requieren al menos dos clases")

biological_ids_all <- if (!is.null(job$biological_ids)) {
  as.character(job$biological_ids)
} else rep("", length(job$classes))
biological_ids <- biological_ids_all[selected]
resampling_units <- ifelse(
  nzchar(biological_ids), paste0("bio:", biological_ids), paste0("sample:", sample_names)
)
unit_classes <- vapply(split(classes, resampling_units), function(values) {
  unique_values <- unique(values)
  if (length(unique_values) != 1L) stop("Una unidad biológica aparece en más de una clase")
  unique_values[[1]]
}, character(1))

preprocess <- function(train, test = NULL) {
  means <- colMeans(train)
  deviations <- apply(train, 2, sd)
  valid <- is.finite(deviations) & deviations > .Machine$double.eps
  train_p <- sweep(train[, valid, drop = FALSE], 2, means[valid], "-")
  test_p <- if (is.null(test)) NULL else sweep(test[, valid, drop = FALSE], 2, means[valid], "-")
  scaling <- as.character(job$preprocessing$scaling)
  if (identical(scaling, "pareto")) {
    divisor <- sqrt(deviations[valid])
    train_p <- sweep(train_p, 2, divisor, "/")
    if (!is.null(test_p)) test_p <- sweep(test_p, 2, divisor, "/")
  } else if (identical(scaling, "unit_variance")) {
    divisor <- deviations[valid]
    train_p <- sweep(train_p, 2, divisor, "/")
    if (!is.null(test_p)) test_p <- sweep(test_p, 2, divisor, "/")
  }
  variable_names <- paste0("v", which(valid))
  colnames(train_p) <- variable_names
  if (!is.null(test_p)) colnames(test_p) <- variable_names
  list(train = train_p, test = test_p)
}

auc_binary <- function(truth, scores) {
  truth <- as.logical(truth)
  positives <- sum(truth); negatives <- sum(!truth)
  if (positives == 0L || negatives == 0L) return(NA_real_)
  score_ranks <- rank(scores, ties.method = "average")
  (sum(score_ranks[truth]) - positives * (positives + 1) / 2) /
    (positives * negatives)
}

classification_ber <- function(truth, predicted) {
  confusion <- table(
    factor(truth, levels = class_levels), factor(predicted, levels = class_levels)
  )
  recalls <- diag(confusion) / rowSums(confusion)
  mean(1 - recalls, na.rm = TRUE)
}

make_fold_ids <- function() {
  folds_by_unit <- integer(length(unit_classes)); names(folds_by_unit) <- names(unit_classes)
  for (class_name in class_levels) {
    class_units <- names(unit_classes)[unit_classes == class_name]
    shuffled <- sample(class_units, length(class_units), replace = FALSE)
    folds_by_unit[shuffled] <- rep(seq_len(data_splits), length.out = length(shuffled))
  }
  unname(folds_by_unit[resampling_units])
}

indicator_matrix <- function(response) {
  output <- 1 * outer(response, class_levels, "==")
  colnames(output) <- class_levels
  output
}

evaluate_pls <- function(response) {
  full <- full_preprocessed
  y <- factor(response, levels = class_levels)
  component_count <- min(
    as.integer(job$current_components), nrow(full$train) - 1L, ncol(full$train)
  )
  model <- mixOmics::plsda(full$train, y, ncomp = component_count, scale = FALSE)
  full_prediction <- predict(model, full$train, dist = "max.dist")$predict[, , component_count]
  full_prediction <- matrix(full_prediction, nrow = nrow(X), ncol = length(class_levels))
  Y_full <- indicator_matrix(response)
  full_tss <- sum(sweep(Y_full, 2, colMeans(Y_full), "-") ^ 2)
  r2y <- 1 - sum((Y_full - full_prediction) ^ 2) / full_tss

  press <- 0; tss <- 0
  ber_values <- rep(NA_real_, metric_repeats)
  decision_sum <- matrix(0, nrow(X), length(class_levels))
  decision_count <- integer(nrow(X))
  repeat_predictions <- lapply(seq_len(metric_repeats), function(index) {
    rep(NA_character_, nrow(X))
  })
  for (task_index in seq_along(validation_tasks)) {
    task <- validation_tasks[[task_index]]
    test_indices <- task$test_indices
    train_indices <- task$train_indices
    fold <- prepared_folds[[task_index]]
    fold_components <- min(component_count, nrow(fold$train) - 1L, ncol(fold$train))
    fold_model <- mixOmics::plsda(
      fold$train, factor(response[train_indices], levels = class_levels),
      ncomp = fold_components, scale = FALSE
    )
    prediction <- predict(fold_model, fold$test, dist = "max.dist")
    repeat_predictions[[task$repeat_index]][test_indices] <-
      as.matrix(prediction$class$max.dist)[, fold_components]
    decisions <- prediction$predict[, , fold_components]
    decisions <- matrix(decisions, nrow = length(test_indices), ncol = length(class_levels))
    decision_sum[test_indices, ] <- decision_sum[test_indices, , drop = FALSE] + decisions
    decision_count[test_indices] <- decision_count[test_indices] + 1L
    Y_train <- indicator_matrix(response[train_indices])
    Y_test <- indicator_matrix(response[test_indices])
    press <- press + sum((Y_test - decisions) ^ 2)
    tss <- tss + sum(sweep(Y_test, 2, colMeans(Y_train), "-") ^ 2)
  }
  for (repeat_index in seq_len(metric_repeats)) {
    covered_repeat <- !is.na(repeat_predictions[[repeat_index]])
    ber_values[repeat_index] <- classification_ber(
      response[covered_repeat], repeat_predictions[[repeat_index]][covered_repeat]
    )
  }
  covered <- decision_count > 0L
  mean_decisions <- matrix(NA_real_, nrow(X), length(class_levels))
  mean_decisions[covered, ] <- sweep(
    decision_sum[covered, , drop = FALSE], 1, decision_count[covered], "/"
  )
  auc_values <- vapply(seq_along(class_levels), function(class_index) {
    auc_binary(response[covered] == class_levels[class_index], mean_decisions[covered, class_index])
  }, numeric(1))
  list(
    r2y = r2y, q2y = 1 - press / tss, ber = mean(ber_values),
    auc_macro = mean(auc_values, na.rm = TRUE), rejected_fraction = 0,
    residual_errors = list(
      calibration = (Y_full - full_prediction) ^ 2,
      cross_validated = (Y_full - mean_decisions) ^ 2
    )
  )
}

validation_strategy <- if (is.null(job$validation$strategy)) {
  "random_subsets"
} else as.character(job$validation$strategy)
if (!validation_strategy %in% c(
  "random_subsets", "monte_carlo", "leave_one_out", "venetian_blinds"
)) stop("Estrategia de validación cruzada no reconocida")
repeats <- as.integer(job$validation$repeats)
data_splits <- if (is.null(job$validation$data_splits)) 5L else {
  as.integer(job$validation$data_splits)
}
train_fraction <- if (is.null(job$validation$train_fraction)) {
  0.8
} else as.numeric(job$validation$train_fraction)
permutation_count <- as.integer(job$permutations$count)
permutation_seed <- as.integer(job$permutations$seed)
analysis_mode <- if (is.null(job$permutations$analysis_mode)) {
  "both"
} else as.character(job$permutations$analysis_mode)
if (!analysis_mode %in% c("empirical", "residual", "both")) {
  stop("Modo de test de permutaciones inválido")
}
if (permutation_count < 1L ||
    (validation_strategy %in% c("random_subsets", "monte_carlo") && repeats < 1L) ||
    (validation_strategy %in% c("random_subsets", "venetian_blinds") && data_splits < 2L)) {
  stop("Parámetros de validación o permutación inválidos")
}
if (validation_strategy == "random_subsets" && any(table(unit_classes) < data_splits)) {
  stop("Cada clase debe tener al menos tantas unidades biológicas como data splits")
}
if (validation_strategy %in% c("monte_carlo", "leave_one_out", "venetian_blinds") &&
    any(table(unit_classes) < 2L)) {
  stop("Cada clase debe tener al menos dos unidades biológicas independientes")
}

# Las particiones y el preprocesamiento de X no dependen de la respuesta permutada.
# Se construyen una sola vez y se reutilizan en el modelo observado y en todos los
# modelos nulos. Esto mantiene exactamente las mismas muestras externas y evita
# repetir una de las operaciones más costosas con espectros de alta dimensión.
set.seed(if (is.null(job$validation$seed)) permutation_seed else as.integer(job$validation$seed))
ordered_units <- unique(resampling_units)
validation_tasks <- list()
if (validation_strategy == "random_subsets") {
  fixed_fold_ids <- lapply(seq_len(repeats), function(repeat_index) make_fold_ids())
  validation_tasks <- unlist(lapply(seq_len(repeats), function(repeat_index) {
    folds <- fixed_fold_ids[[repeat_index]]
    lapply(seq_len(data_splits), function(split_index) list(
      repeat_index = repeat_index, split_index = split_index,
      train_indices = which(folds != split_index), test_indices = which(folds == split_index)
    ))
  }), recursive = FALSE)
  metric_repeats <- repeats
} else if (validation_strategy == "monte_carlo") {
  validation_tasks <- lapply(seq_len(repeats), function(repeat_index) {
    test_units <- unlist(lapply(class_levels, function(class_name) {
      class_units <- names(unit_classes)[unit_classes == class_name]
      test_count <- max(1L, min(
        length(class_units) - 1L,
        as.integer(round(length(class_units) * (1 - train_fraction)))
      ))
      sample(class_units, test_count, replace = FALSE)
    }), use.names = FALSE)
    test_indices <- which(resampling_units %in% test_units)
    list(
      repeat_index = repeat_index, split_index = 1L,
      train_indices = setdiff(seq_len(nrow(X)), test_indices), test_indices = test_indices
    )
  })
  metric_repeats <- repeats
} else if (validation_strategy == "leave_one_out") {
  validation_tasks <- lapply(seq_along(ordered_units), function(split_index) {
    test_indices <- which(resampling_units == ordered_units[[split_index]])
    list(
      repeat_index = 1L, split_index = split_index,
      train_indices = setdiff(seq_len(nrow(X)), test_indices), test_indices = test_indices
    )
  })
  repeats <- 1L
  data_splits <- length(validation_tasks)
  metric_repeats <- 1L
} else {
  if (data_splits >= length(ordered_units)) {
    stop("Venetian blinds requiere menos bloques que unidades biológicas")
  }
  folds_by_unit <- rep(seq_len(data_splits), length.out = length(ordered_units))
  names(folds_by_unit) <- ordered_units
  folds <- unname(folds_by_unit[resampling_units])
  validation_tasks <- lapply(seq_len(data_splits), function(split_index) list(
    repeat_index = 1L, split_index = split_index,
    train_indices = which(folds != split_index), test_indices = which(folds == split_index)
  ))
  repeats <- 1L
  metric_repeats <- 1L
}
full_preprocessed <- preprocess(X)
prepared_folds <- lapply(validation_tasks, function(task) {
  preprocess(
    X[task$train_indices, , drop = FALSE], X[task$test_indices, , drop = FALSE]
  )
})

response_is_estimable <- function(response) {
  all(vapply(validation_tasks, function(task) {
    length(unique(response[task$train_indices])) == length(class_levels)
  }, logical(1)))
}

evaluate <- evaluate_pls
test_started <- proc.time()[["elapsed"]]
set.seed(permutation_seed)
observed_seed <- sample.int(.Machine$integer.max, 1L)
shuffle_seeds <- sample.int(.Machine$integer.max, permutation_count)
evaluation_seeds <- sample.int(.Machine$integer.max, permutation_count)
set.seed(observed_seed)
observed_started <- proc.time()[["elapsed"]]
observed <- evaluate(classes)
observed_seconds <- proc.time()[["elapsed"]] - observed_started
unit_names <- names(unit_classes)
original_indicator <- as.numeric(indicator_matrix(classes))
permuted_responses <- lapply(seq_len(permutation_count), function(permutation_index) {
  set.seed(shuffle_seeds[[permutation_index]])
  attempts <- 0L
  repeat {
    attempts <- attempts + 1L
    shuffled_unit_classes <- sample(unname(unit_classes), replace = FALSE)
    names(shuffled_unit_classes) <- unit_names
    candidate <- unname(shuffled_unit_classes[resampling_units])
    if (response_is_estimable(candidate)) return(candidate)
    if (attempts >= 10000L) {
      stop("No fue posible generar una respuesta permutada estimable con los folds fijos")
    }
  }
})
distributed_tasks <- suppressWarnings(as.integer(Sys.getenv("ARII_DISTRIBUTED_TASKS", "1")))
distributed_index <- suppressWarnings(as.integer(Sys.getenv(
  "ARII_DISTRIBUTED_INDEX", Sys.getenv("SLURM_PROCID", "0")
)))
if (!is.finite(distributed_tasks) || distributed_tasks < 1L) distributed_tasks <- 1L
distributed_tasks <- min(distributed_tasks, permutation_count)
if (!is.finite(distributed_index) || distributed_index < 0L ||
    distributed_index >= distributed_tasks) {
  stop("Índice de tarea distribuida inválido")
}
permutation_indices <- seq.int(
  distributed_index + 1L, permutation_count, by = distributed_tasks
)
correlation_to_original <- vapply(permuted_responses[permutation_indices], function(permuted_response) {
  suppressWarnings(cor(
    original_indicator, as.numeric(indicator_matrix(permuted_response)),
    method = "pearson"
  ))
}, numeric(1))

requested_workers <- suppressWarnings(as.integer(Sys.getenv("ARII_PARALLEL_WORKERS", "1")))
if (!is.finite(requested_workers) || requested_workers < 1L) requested_workers <- 1L
parallel_workers <- min(requested_workers, permutation_count)
parallel_workers <- min(parallel_workers, length(permutation_indices))
message(sprintf(
  "ARII_PERMUTATION_PROGRESS: 0/%d; workers=%d; task=%d/%d",
  length(permutation_indices), parallel_workers, distributed_index + 1L, distributed_tasks
))

evaluate_permutation <- function(permutation_index) {
  permutation_started <- proc.time()[["elapsed"]]
  set.seed(evaluation_seeds[[permutation_index]])
  value <- evaluate(permuted_responses[[permutation_index]])
  list(
    value = value,
    seconds = proc.time()[["elapsed"]] - permutation_started
  )
}

evaluated <- if (parallel_workers > 1L && .Platform$OS.type == "windows") {
  export_names <- ls(envir = .GlobalEnv)
  cluster <- parallel::makeCluster(parallel_workers)
  tryCatch({
    parallel::clusterExport(cluster, export_names, envir = .GlobalEnv)
    package_name <- "mixOmics"
    parallel::clusterCall(cluster, function(name) {
      suppressPackageStartupMessages(library(name, character.only = TRUE))
      NULL
    }, package_name)
    parallel::parLapply(cluster, permutation_indices, evaluate_permutation)
  }, finally = parallel::stopCluster(cluster))
} else if (parallel_workers > 1L) {
  parallel::mclapply(
    permutation_indices, evaluate_permutation,
    mc.cores = parallel_workers, mc.preschedule = TRUE, mc.set.seed = FALSE
  )
} else {
  lapply(permutation_indices, evaluate_permutation)
}
failed_indices <- which(vapply(evaluated, inherits, logical(1), "try-error"))
if (length(failed_indices) > 0L) {
  stop(sprintf(
    "Falló la evaluación de las permutaciones: %s",
    paste(failed_indices, collapse = ", ")
  ))
}
null_results <- lapply(evaluated, `[[`, "value")
permutation_seconds <- vapply(evaluated, `[[`, numeric(1), "seconds")
message(sprintf(
  "ARII_PERMUTATION_PROGRESS: %d/%d; workers=%d; task=%d/%d",
  length(permutation_indices), length(permutation_indices), parallel_workers,
  distributed_index + 1L, distributed_tasks
))

metric_names <- c("r2y", "q2y", "ber", "auc_macro")
null_metrics <- lapply(metric_names, function(metric) {
  vapply(null_results, function(value) as.numeric(value[[metric]]), numeric(1))
})
names(null_metrics) <- metric_names
empirical_p <- c(
  r2y = (1 + sum(null_metrics$r2y >= observed$r2y)) / (permutation_count + 1),
  q2y = (1 + sum(null_metrics$q2y >= observed$q2y)) / (permutation_count + 1),
  ber = (1 + sum(null_metrics$ber <= observed$ber)) / (permutation_count + 1),
  auc_macro = (1 + sum(null_metrics$auc_macro >= observed$auc_macro)) / (permutation_count + 1)
)

standardized_residual_ssq <- function(errors, response) {
  covered <- apply(errors, 1, function(values) all(is.finite(values)))
  errors <- errors[covered, , drop = FALSE]
  response <- response[covered]
  y <- indicator_matrix(response)
  denominator <- colSums(sweep(y, 2, colMeans(y), "-") ^ 2)
  by_class <- colSums(errors) / denominator
  output <- c(global = sum(errors) / sum(denominator), by_class)
  as.list(output)
}

paired_residual_tests <- function(observed_errors, null_errors, seed) {
  observed_errors <- as.numeric(observed_errors)
  null_errors <- as.numeric(null_errors)
  differences <- null_errors - observed_errors
  finite <- is.finite(differences)
  differences <- differences[finite]
  observed_errors <- observed_errors[finite]
  null_errors <- null_errors[finite]
  nonzero <- differences[abs(differences) > sqrt(.Machine$double.eps)]
  if (length(nonzero) == 0L) {
    wilcoxon_p <- 1
    sign_p <- 1
    randomization_p <- 1
  } else {
    absolute <- abs(nonzero)
    ranks <- rank(absolute, ties.method = "average")
    positive_rank_sum <- sum(ranks[nonzero > 0])
    sample_count <- length(nonzero)
    tie_sizes <- as.numeric(table(absolute))
    expected_rank_sum <- sample_count * (sample_count + 1) / 4
    rank_variance <- (
      sample_count * (sample_count + 1) * (2 * sample_count + 1) -
        sum(tie_sizes ^ 3 - tie_sizes)
    ) / 24
    wilcoxon_p <- if (rank_variance > 0) {
      pnorm(
        (positive_rank_sum - expected_rank_sum - 0.5) / sqrt(rank_variance),
        lower.tail = FALSE
      )
    } else 1
    positive <- sum(nonzero > 0)
    sign_p <- pbinom(positive - 1L, length(nonzero), 0.5, lower.tail = FALSE)
    randomization_iterations <- 9999L
    sign_count <- length(nonzero) * randomization_iterations
    states <- numeric(sign_count)
    state <- as.numeric(seed %% 2147483647L)
    if (state <= 0) state <- 1
    for (state_index in seq_len(sign_count)) {
      state <- (48271 * state) %% 2147483647
      states[[state_index]] <- state
    }
    signs <- matrix(
      ifelse(states %% 2 < 1, -1, 1),
      nrow = length(nonzero)
    )
    permuted <- signs * nonzero
    permuted_sd <- apply(permuted, 2, sd)
    permuted_t <- colMeans(permuted) / (permuted_sd / sqrt(length(nonzero)))
    observed_sd <- sd(nonzero)
    observed_t <- if (is.finite(observed_sd) && observed_sd > 0) {
      mean(nonzero) / (observed_sd / sqrt(length(nonzero)))
    } else if (mean(nonzero) > 0) Inf else -Inf
    randomization_p <- (
      1 + sum(permuted_t >= observed_t, na.rm = TRUE)
    ) / (randomization_iterations + 1)
  }
  list(
    wilcoxon = wilcoxon_p,
    sign_test = as.numeric(sign_p),
    randomization_t = as.numeric(randomization_p),
    samples = length(differences),
    observed_mean_squared_error = mean(observed_errors),
    permuted_mean_squared_error = mean(null_errors),
    mean_error_improvement = mean(differences),
    alternative = "observed_error_lower_than_permuted"
  )
}

build_residual_tests <- function(observed_errors, mean_null_errors, seed) {
  modes <- c("calibration", "cross_validated")
  output <- list()
  for (mode_index in seq_along(modes)) {
    mode <- modes[[mode_index]]
    observed_matrix <- as.matrix(observed_errors[[mode]])
    null_matrix <- as.matrix(mean_null_errors[[mode]])
    scopes <- c("global", class_levels)
    output[[mode]] <- setNames(lapply(seq_along(scopes), function(scope_index) {
      if (scope_index == 1L) {
        observed_values <- rowSums(observed_matrix)
        null_values <- rowSums(null_matrix)
      } else {
        observed_values <- observed_matrix[, scope_index - 1L]
        null_values <- null_matrix[, scope_index - 1L]
      }
      paired_residual_tests(
        observed_values, null_values,
        seed + mode_index * 1009L + scope_index * 9176L
      )
    }), scopes)
  }
  output
}

residual_comparison <- NULL
if (!identical(analysis_mode, "empirical")) {
  observed_residual_errors <- observed$residual_errors
  null_error_sum <- list(
    calibration = Reduce(
      `+`, lapply(null_results, function(value) value$residual_errors$calibration)
    ),
    cross_validated = Reduce(
      `+`, lapply(null_results, function(value) value$residual_errors$cross_validated)
    )
  )
  mean_null_errors <- lapply(null_error_sum, `/`, length(null_results))
  observed_residual_ssq <- list(
    calibration = standardized_residual_ssq(observed_residual_errors$calibration, classes),
    cross_validated = standardized_residual_ssq(
      observed_residual_errors$cross_validated, classes
    )
  )
  null_residual_ssq <- list(calibration = list(), cross_validated = list())
  for (mode in names(null_residual_ssq)) {
    summaries <- lapply(seq_along(null_results), function(offset) {
      standardized_residual_ssq(
        null_results[[offset]]$residual_errors[[mode]],
        permuted_responses[[permutation_indices[[offset]]]]
      )
    })
    for (scope in c("global", class_levels)) {
      null_residual_ssq[[mode]][[scope]] <- vapply(
        summaries, function(value) as.numeric(value[[scope]]), numeric(1)
      )
    }
  }
  residual_comparison <- list(
    compatibility = "PLS_Toolbox_conceptual_not_bit_exact",
    error = "squared_dummy_response_residual",
    class_levels = class_levels,
    observed_standardized_ssq = observed_residual_ssq,
    null_standardized_ssq = null_residual_ssq,
    observed_error_by_sample = observed_residual_errors,
    null_error_sum_by_sample = null_error_sum,
    evaluated_permutations = length(null_results),
    tests = build_residual_tests(
      observed_residual_errors, mean_null_errors, permutation_seed + 700001L
    ),
    tests_basis = "paired_sample_errors_against_mean_permuted_error",
    randomization_t_iterations = 9999L
  )
}

# Las matrices por muestra pertenecen al diagnóstico residual, no a las métricas
# empíricas principales.
observed$residual_errors <- NULL
for (index in seq_along(null_results)) null_results[[index]]$residual_errors <- NULL

result <- list(
  schema_version = "1.1",
  method = method,
  test = "response_label_permutation",
  requested_analysis_mode = analysis_mode,
  selection_policy = "fixed_current_complexity",
  permutations = permutation_count,
  permutation_indices = permutation_indices,
  seed = permutation_seed,
  exchangeability_unit = if (any(nzchar(biological_ids))) {
    "biological_id_or_sample"
  } else "sample",
  validation = list(
    strategy = switch(
      validation_strategy,
      random_subsets = "repeated_stratified_random_subsets",
      monte_carlo = "stratified_monte_carlo_holdout",
      leave_one_out = "leave_one_unit_out",
      venetian_blinds = "grouped_venetian_blinds"
    ),
    validation_method = validation_strategy,
    repeats = repeats, data_splits = data_splits,
    submodels_per_permutation = length(validation_tasks),
    fold_policy = "fixed_and_reused_across_observed_and_permuted_responses",
    preprocessing_policy = "training_only_cached_per_fold"
  ),
  observed = observed,
  null = null_metrics,
  correlation_to_original = correlation_to_original,
  empirical_p = as.list(empirical_p),
  residual_comparison = residual_comparison,
  null_rejected_fraction = vapply(
    null_results, function(value) as.numeric(value$rejected_fraction), numeric(1)
  ),
  interpretation = list(
    higher_is_better = c("r2y", "q2y", "auc_macro"),
    lower_is_better = "ber",
    correction = "plus_one"
  ),
  optimization = list(
    fixed_current_model = TRUE,
    reused_cv_partitions = TRUE,
    reused_x_preprocessing = TRUE,
    shared_predictions_for_empirical_and_residual = !identical(analysis_mode, "empirical")
  ),
  timing = list(
    total_seconds = proc.time()[["elapsed"]] - test_started,
    observed_seconds = observed_seconds,
    permutation_seconds = permutation_seconds,
    mean_permutation_seconds = mean(permutation_seconds),
    parallel_workers = parallel_workers,
    distributed_tasks = distributed_tasks,
    distributed_index = distributed_index
  )
)

write_json(result, args[[2]], auto_unbox = TRUE, digits = 15, pretty = FALSE, na = "null")

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(mixOmics))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Uso: plsda_worker.R <job.json> <result.json>")
job <- fromJSON(
  paste(readLines(args[[1]], warn = FALSE, encoding = "UTF-8"), collapse = "\n"),
  simplifyVector = TRUE
)

delimiter <- if (is.null(job$dataset$delimiter)) "," else as.character(job$dataset$delimiter)
raw <- read.table(
  job$dataset$path, header = TRUE, sep = delimiter, check.names = FALSE,
  stringsAsFactors = FALSE, quote = "\"", comment.char = ""
)
orientation <- if (is.null(job$dataset$orientation)) {
  "variables_by_samples"
} else as.character(job$dataset$orientation)
if (orientation == "samples_by_variables") {
  sample_names <- as.character(raw[[1]])
  feature_ids <- names(raw)[-1]
  X <- as.matrix(raw[-1])
} else if (orientation == "variables_by_samples") {
  feature_ids <- as.character(raw[[1]])
  sample_names <- names(raw)[-1]
  X <- t(as.matrix(raw[-1]))
} else stop("Orientación de matriz no reconocida")
storage.mode(X) <- "double"
if (anyNA(X) || any(!is.finite(X))) {
  stop("La matriz contiene valores ausentes, infinitos o no numéricos")
}
numeric_feature_axis <- suppressWarnings(as.numeric(feature_ids))
feature_axis_numeric <- !anyNA(numeric_feature_axis) && all(is.finite(numeric_feature_axis))
ppm <- if (feature_axis_numeric) numeric_feature_axis else seq_along(feature_ids)
selected <- as.integer(job$selected_sample_indices) + 1L
X <- X[selected, , drop = FALSE]
sample_names <- sample_names[selected]
classes <- as.character(job$classes[selected])
y <- factor(classes)
if (nlevels(y) < 2L) stop("PLS-DA requiere al menos dos clases")
if (any(table(y) < 2L)) stop("Cada clase debe contener al menos dos muestras")
biological_ids_all <- if (!is.null(job$biological_ids)) {
  as.character(job$biological_ids)
} else rep("", length(job$classes))
biological_ids <- biological_ids_all[selected]
resampling_units <- ifelse(
  nzchar(biological_ids), paste0("bio:", biological_ids), paste0("sample:", sample_names)
)
unit_classes <- vapply(split(classes, resampling_units), function(values) {
  unique_values <- unique(values)
  if (length(unique_values) != 1L) stop("Un individuo biológico aparece en más de una clase")
  unique_values[[1]]
}, character(1))

preprocess <- function(train, test = NULL, scaling = "pareto") {
  means <- colMeans(train)
  deviations <- apply(train, 2, sd)
  valid <- is.finite(deviations) & deviations > .Machine$double.eps
  train_processed <- sweep(train[, valid, drop = FALSE], 2, means[valid], "-")
  test_processed <- if (!is.null(test)) {
    sweep(test[, valid, drop = FALSE], 2, means[valid], "-")
  } else NULL
  variable_names <- paste0("v", which(valid))
  colnames(train_processed) <- variable_names
  if (!is.null(test_processed)) colnames(test_processed) <- variable_names
  if (identical(scaling, "pareto")) {
    divisor <- sqrt(deviations[valid])
    train_processed <- sweep(train_processed, 2, divisor, "/")
    if (!is.null(test_processed)) test_processed <- sweep(test_processed, 2, divisor, "/")
  } else if (identical(scaling, "unit_variance")) {
    divisor <- deviations[valid]
    train_processed <- sweep(train_processed, 2, divisor, "/")
    if (!is.null(test_processed)) test_processed <- sweep(test_processed, 2, divisor, "/")
  }
  list(train = train_processed, test = test_processed, valid = valid, sd = deviations[valid])
}

auc_binary <- function(truth, scores) {
  truth <- as.logical(truth)
  positives <- sum(truth); negatives <- sum(!truth)
  if (positives == 0L || negatives == 0L) return(NA_real_)
  score_ranks <- rank(scores, ties.method = "average")
  (sum(score_ranks[truth]) - positives * (positives + 1) / 2) /
    (positives * negatives)
}

classification_metrics <- function(truth, predicted, levels) {
  truth <- factor(truth, levels = levels)
  predicted <- factor(predicted, levels = levels)
  confusion <- table(truth, predicted)
  recalls <- diag(confusion) / rowSums(confusion)
  list(
    accuracy = mean(predicted == truth),
    ber = mean(1 - recalls, na.rm = TRUE),
    correct = sum(predicted == truth)
  )
}

full_processed <- preprocess(X, scaling = job$preprocessing$scaling)
X_model <- full_processed$train
ppm_model <- ppm[full_processed$valid]
feature_ids_model <- feature_ids[full_processed$valid]
validation_strategy <- if (is.null(job$validation$strategy)) {
  "random_subsets"
} else as.character(job$validation$strategy)
if (!validation_strategy %in% c(
  "random_subsets", "monte_carlo", "leave_one_out", "venetian_blinds"
)) stop("Estrategia de validación cruzada no reconocida")
repeats <- as.integer(job$validation$repeats)
data_splits <- if (is.null(job$validation$data_splits)) {
  max(2L, as.integer(round(1 / (1 - as.numeric(job$validation$train_fraction)))))
} else as.integer(job$validation$data_splits)
train_fraction_requested <- if (is.null(job$validation$train_fraction)) {
  0.8
} else as.numeric(job$validation$train_fraction)
if (validation_strategy %in% c("random_subsets", "monte_carlo") && repeats < 1L) {
  stop("El número de iteraciones debe ser positivo")
}
if (validation_strategy %in% c("random_subsets", "venetian_blinds") && data_splits < 2L) {
  stop("El número de data splits debe ser al menos 2")
}
if (validation_strategy == "monte_carlo" &&
    (!is.finite(train_fraction_requested) || train_fraction_requested <= 0 ||
     train_fraction_requested >= 1)) {
  stop("La fracción de entrenamiento de Monte Carlo debe estar entre 0 y 1")
}
units_per_class <- table(unit_classes)
if (validation_strategy == "random_subsets" && any(units_per_class < data_splits)) {
  stop("Cada clase debe tener al menos tantas unidades biológicas como data splits")
}
if (validation_strategy %in% c("monte_carlo", "leave_one_out", "venetian_blinds") &&
    any(units_per_class < 2L)) {
  stop("Cada clase debe tener al menos dos unidades biológicas independientes")
}
ordered_units <- unique(resampling_units)
if (validation_strategy == "venetian_blinds" && data_splits >= length(ordered_units)) {
  stop("Venetian blinds requiere menos bloques que unidades biológicas")
}
make_fold_ids <- function() {
  unit_folds <- integer(length(unit_classes)); names(unit_folds) <- names(unit_classes)
  for (class_name in names(units_per_class)) {
    class_units <- names(unit_classes)[unit_classes == class_name]
    shuffled <- sample(class_units, length(class_units), replace = FALSE)
    unit_folds[shuffled] <- rep(seq_len(data_splits), length.out = length(shuffled))
  }
  unname(unit_folds[resampling_units])
}
validation_seed <- if (is.null(job$validation$seed)) 1234L else as.integer(job$validation$seed)
set.seed(validation_seed)
validation_tasks <- list()
if (validation_strategy == "random_subsets") {
  fold_assignments <- lapply(seq_len(repeats), function(i) make_fold_ids())
  validation_tasks <- unlist(lapply(seq_len(repeats), function(repeat_index) {
    folds <- fold_assignments[[repeat_index]]
    lapply(seq_len(data_splits), function(split_index) list(
      repeat_index = repeat_index, split_index = split_index,
      train_indices = which(folds != split_index), test_indices = which(folds == split_index)
    ))
  }), recursive = FALSE)
  metric_repeats <- repeats
} else if (validation_strategy == "monte_carlo") {
  validation_tasks <- lapply(seq_len(repeats), function(repeat_index) {
    test_units <- unlist(lapply(names(units_per_class), function(class_name) {
      class_units <- names(unit_classes)[unit_classes == class_name]
      test_count <- max(1L, min(
        length(class_units) - 1L,
        as.integer(round(length(class_units) * (1 - train_fraction_requested)))
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
if (any(vapply(validation_tasks, function(task) {
  length(task$test_indices) == 0L ||
    length(unique(classes[task$train_indices])) != length(levels(y))
}, logical(1)))) stop("Algún submodelo no conserva todas las clases en entrenamiento")
expected_train_size <- min(vapply(
  validation_tasks, function(task) length(task$train_indices), integer(1)
))
ncomp <- min(
  as.integer(job$n_components),
  nrow(X_model) - 1L,
  ncol(X_model),
  expected_train_size - 1L
)
model <- mixOmics::plsda(X_model, y, ncomp = ncomp, scale = FALSE)
component_names <- paste0("LV", seq_len(ncomp))
colnames(model$variates$X) <- component_names
colnames(model$loadings$X) <- component_names
full_prediction_result <- predict(model, X_model, dist = "max.dist")
full_prediction <- full_prediction_result$predict
class_levels <- levels(y)
Y_full <- 1 * outer(classes, class_levels, "==")
colnames(Y_full) <- class_levels
full_y_tss <- sum(sweep(Y_full, 2, colMeans(Y_full), "-") ^ 2)
r2y <- vapply(seq_len(ncomp), function(component_index) {
  prediction_matrix <- full_prediction[, , component_index, drop = FALSE]
  dim(prediction_matrix) <- c(nrow(Y_full), ncol(Y_full))
  1 - sum((Y_full - prediction_matrix) ^ 2) / full_y_tss
}, numeric(1))
calibration_predictions <- as.matrix(full_prediction_result$class$max.dist)
calibration_accuracy <- numeric(ncomp)
calibration_ber <- numeric(ncomp)
calibration_correct <- integer(ncomp)
calibration_auc <- matrix(NA_real_, ncomp, length(class_levels))
for (component_index in seq_len(ncomp)) {
  metrics <- classification_metrics(
    classes, calibration_predictions[, component_index], class_levels
  )
  calibration_accuracy[component_index] <- metrics$accuracy
  calibration_ber[component_index] <- metrics$ber
  calibration_correct[component_index] <- metrics$correct
  for (class_index in seq_along(class_levels)) {
    calibration_auc[component_index, class_index] <- auc_binary(
      classes == class_levels[class_index], full_prediction[, class_index, component_index]
    )
  }
}
hotelling_dimensions <- 2L
hotelling_limit <- function(confidence) {
  hotelling_dimensions * (nrow(X_model) - 1) /
    (nrow(X_model) - hotelling_dimensions) *
    qf(confidence, hotelling_dimensions, nrow(X_model) - hotelling_dimensions)
}

accuracy_matrix <- matrix(NA_real_, metric_repeats, ncomp)
ber_matrix <- matrix(NA_real_, metric_repeats, ncomp)
confusions <- lapply(seq_len(ncomp), function(i) {
  matrix(0L, nrow = length(class_levels), ncol = length(class_levels),
         dimnames = list(truth = class_levels, predicted = class_levels))
})
prediction_records <- vector("list", length(validation_tasks))
q2y_press <- numeric(ncomp)
q2y_tss <- numeric(ncomp)
cv_decision_sum <- array(0, dim = c(nrow(X), length(class_levels), ncomp))
cv_decision_count <- matrix(0L, nrow(X), ncomp)
repeat_predictions <- lapply(seq_len(metric_repeats), function(index) {
  matrix(NA_character_, nrow(X), ncomp)
})
fold_tasks <- validation_tasks

evaluate_fold <- function(task) {
  repeat_index <- task$repeat_index
  split_index <- task$split_index
  test_indices <- task$test_indices
  train_indices <- task$train_indices
  fold <- preprocess(
    X[train_indices, , drop = FALSE], X[test_indices, , drop = FALSE],
    job$preprocessing$scaling
  )
  fold_y <- factor(classes[train_indices], levels = class_levels)
  fold_ncomp <- min(ncomp, nrow(fold$train) - 1L, ncol(fold$train))
  fold_model <- mixOmics::plsda(fold$train, fold_y, ncomp = fold_ncomp, scale = FALSE)
  prediction <- predict(fold_model, fold$test, dist = "max.dist")
  predicted_matrix <- as.matrix(prediction$class$max.dist)
  decisions <- prediction$predict[, , seq_len(fold_ncomp), drop = FALSE]
  Y_train <- 1 * outer(classes[train_indices], class_levels, "==")
  Y_test <- 1 * outer(classes[test_indices], class_levels, "==")
  fold_y_tss <- sum(sweep(Y_test, 2, colMeans(Y_train), "-") ^ 2)
  fold_press <- vapply(seq_len(fold_ncomp), function(component_index) {
    fold_y_prediction <- decisions[, , component_index, drop = FALSE]
    dim(fold_y_prediction) <- c(nrow(Y_test), ncol(Y_test))
    sum((Y_test - fold_y_prediction) ^ 2)
  }, numeric(1))
  list(
    repeat_index = repeat_index, split_index = split_index,
    test_indices = test_indices, train_indices = train_indices,
    fold_ncomp = fold_ncomp, predicted = predicted_matrix,
    decisions = decisions, press = fold_press, tss = fold_y_tss
  )
}

requested_workers <- suppressWarnings(as.integer(Sys.getenv("ARII_PARALLEL_WORKERS", "1")))
if (!is.finite(requested_workers) || requested_workers < 1L) requested_workers <- 1L
parallel_workers <- min(requested_workers, length(fold_tasks))
message(sprintf("ARII_CV_PROGRESS: 0/%d; workers=%d", length(fold_tasks), parallel_workers))
fold_results <- if (parallel_workers > 1L && .Platform$OS.type == "windows") {
  cluster <- parallel::makeCluster(parallel_workers)
  tryCatch({
    parallel::clusterExport(
      cluster,
      c("X", "classes", "class_levels", "ncomp", "job",
        "preprocess", "evaluate_fold"),
      envir = .GlobalEnv
    )
    parallel::clusterCall(cluster, function(name) {
      suppressPackageStartupMessages(library(name, character.only = TRUE))
      NULL
    }, "mixOmics")
    parallel::parLapply(cluster, fold_tasks, evaluate_fold)
  }, finally = parallel::stopCluster(cluster))
} else if (parallel_workers > 1L) {
  parallel::mclapply(
    fold_tasks, evaluate_fold, mc.cores = parallel_workers,
    mc.preschedule = TRUE, mc.set.seed = FALSE
  )
} else lapply(fold_tasks, evaluate_fold)
failed_indices <- which(vapply(fold_results, inherits, logical(1), "try-error"))
if (length(failed_indices) > 0L) {
  stop(sprintf("Falló la validación en los folds: %s", paste(failed_indices, collapse = ", ")))
}

for (record_index in seq_along(fold_results)) {
  fold_result <- fold_results[[record_index]]
  component_indices <- seq_len(fold_result$fold_ncomp)
  repeat_index <- fold_result$repeat_index
  test_indices <- fold_result$test_indices
  repeat_predictions[[repeat_index]][test_indices, component_indices] <-
    fold_result$predicted
  cv_decision_sum[test_indices, , component_indices] <-
    cv_decision_sum[test_indices, , component_indices, drop = FALSE] +
    fold_result$decisions
  cv_decision_count[test_indices, component_indices] <-
    cv_decision_count[test_indices, component_indices, drop = FALSE] + 1L
  q2y_press[component_indices] <- q2y_press[component_indices] + fold_result$press
  q2y_tss[component_indices] <- q2y_tss[component_indices] + fold_result$tss
  prediction_records[[record_index]] <- list(
    `repeat` = repeat_index,
    split = fold_result$split_index,
    train_samples = sample_names[fold_result$train_indices],
    validation_samples = sample_names[test_indices],
    truth = classes[test_indices],
    predicted = unname(fold_result$predicted),
    decision_values = unname(fold_result$decisions)
  )
}
message(sprintf(
  "ARII_CV_PROGRESS: %d/%d; workers=%d",
  length(fold_tasks), length(fold_tasks), parallel_workers
))

for (repeat_index in seq_len(metric_repeats)) {
  for (component_index in seq_len(ncomp)) {
    valid_prediction <- !is.na(repeat_predictions[[repeat_index]][, component_index])
    predicted <- factor(
      repeat_predictions[[repeat_index]][valid_prediction, component_index],
      levels = class_levels
    )
    truth <- factor(classes[valid_prediction], levels = class_levels)
    confusion <- table(truth, predicted)
    confusions[[component_index]] <- confusions[[component_index]] + confusion
    accuracy_matrix[repeat_index, component_index] <- mean(predicted == truth)
    recalls <- diag(confusion) / rowSums(confusion)
    ber_matrix[repeat_index, component_index] <- mean(1 - recalls, na.rm = TRUE)
  }
}

cv_mean_decisions <- cv_decision_sum
for (component_index in seq_len(ncomp)) {
  covered <- cv_decision_count[, component_index] > 0L
  cv_mean_decisions[covered, , component_index] <- sweep(
    cv_decision_sum[covered, , component_index, drop = FALSE],
    1, cv_decision_count[covered, component_index], "/"
  )
  cv_mean_decisions[!covered, , component_index] <- NA_real_
}
cv_auc <- matrix(NA_real_, ncomp, length(class_levels))
for (component_index in seq_len(ncomp)) {
  covered <- cv_decision_count[, component_index] > 0L
  for (class_index in seq_along(class_levels)) {
    cv_auc[component_index, class_index] <- auc_binary(
      classes[covered] == class_levels[class_index],
      cv_mean_decisions[covered, class_index, component_index]
    )
  }
}
mean_ber <- colMeans(ber_matrix, na.rm = TRUE)
sd_ber <- apply(ber_matrix, 2, sd, na.rm = TRUE)
se_ber <- sd_ber / sqrt(metric_repeats)
se_ber[!is.finite(se_ber)] <- 0
minimum_component <- which.min(mean_ber)
suggested_component <- which(mean_ber <= mean_ber[minimum_component] + se_ber[minimum_component])[1]
test_fractions <- vapply(
  validation_tasks, function(task) length(task$test_indices) / nrow(X), numeric(1)
)
validation_counts <- tabulate(
  unlist(lapply(validation_tasks, function(task) task$test_indices)), nbins = nrow(X)
)

orthogonalized <- isTRUE(job$orthogonalize_plsda)
orthogonalization <- NULL
if (orthogonalized) {
  if (length(class_levels) != 2L) {
    stop("OPLS-DA requiere exactamente dos clases")
  }
  orthogonalization <- list(
    enabled = TRUE,
    type = "post_fit_binary_response_rotation",
    predictions_unchanged = TRUE,
    predictive_components = 1L,
    orthogonal_components = ncomp - 1L
  )
}

build_candidate_model <- function(component_count) {
  original_scores <- model$variates$X[, seq_len(component_count), drop = FALSE]
  if (!orthogonalized) {
    candidate_names <- paste0("LV", seq_len(component_count))
    candidate_scores <- original_scores
    candidate_loadings <- model$loadings$X[, seq_len(component_count), drop = FALSE]
    candidate_explained <- as.numeric(model$prop_expl_var$X[seq_len(component_count)])
  } else {
    predictive_response <- full_prediction[, 2L, component_count]
    predictive_response <- predictive_response - mean(predictive_response)
    predictive_norm <- sqrt(sum(predictive_response ^ 2))
    if (!is.finite(predictive_norm) || predictive_norm <= .Machine$double.eps) {
      stop("No se pudo obtener una dirección predictiva para ortogonalizar el PLS-DA")
    }
    predictive_basis <- predictive_response / predictive_norm
    residual_scores <- original_scores - tcrossprod(
      predictive_basis, as.numeric(crossprod(predictive_basis, original_scores))
    )
    orthogonal_basis <- matrix(numeric(0), nrow(X_model), 0L)
    if (component_count > 1L) {
      residual_qr <- qr(residual_scores, tol = 1e-10)
      if (residual_qr$rank < component_count - 1L) {
        stop("La base latente no tiene rango suficiente para la ortogonalización solicitada")
      }
      orthogonal_basis <- qr.Q(residual_qr)[, seq_len(component_count - 1L), drop = FALSE]
    }
    rotated_basis <- cbind(predictive_basis, orthogonal_basis)
    score_scales <- sqrt(colSums(original_scores ^ 2))
    candidate_scores <- sweep(rotated_basis, 2, score_scales, "*")
    candidate_loadings <- t(solve(
      crossprod(candidate_scores), crossprod(candidate_scores, X_model)
    ))
    candidate_explained <- vapply(seq_len(component_count), function(component_index) {
      contribution <- tcrossprod(
        candidate_scores[, component_index], candidate_loadings[, component_index]
      )
      sum(contribution ^ 2) / sum(X_model ^ 2)
    }, numeric(1))
    candidate_names <- c(
      "Predictiva",
      if (component_count > 1L) paste0(
        "Ortogonal ", seq_len(component_count - 1L)
      ) else character(0)
    )
  }
  colnames(candidate_scores) <- candidate_names
  colnames(candidate_loadings) <- candidate_names
  list(
    component_count = component_count,
    component_names = I(candidate_names),
    explained_variance = I(candidate_explained),
    cumulative_variance = I(cumsum(candidate_explained)),
    scores = unname(candidate_scores),
    loadings = unname(candidate_loadings)
  )
}

candidate_models <- lapply(seq_len(ncomp), build_candidate_model)
current_component <- suggested_component
current_model <- candidate_models[[current_component]]
if (orthogonalized) {
  orthogonalization$orthogonal_components <- current_component - 1L
  orthogonalization$maximum_evaluated_components <- ncomp
}

confusion_output <- lapply(seq_len(ncomp), function(component_index) {
  list(
    component = component_index,
    labels = class_levels,
    matrix = matrix(
      as.integer(confusions[[component_index]]),
      nrow = length(class_levels),
      ncol = length(class_levels)
    )
  )
})

result <- list(
  schema_version = "1.0",
  method = if (orthogonalized) "orthogonalized_plsda" else "plsda",
  engine = list(
    name = "mixOmics",
    version = as.character(packageVersion("mixOmics")),
    r_version = R.version.string
  ),
  dimensions = list(
    samples = nrow(X_model),
    variables = ncol(X_model),
    removed_constant_variables = sum(!full_processed$valid)
  ),
  preprocessing = list(
    mean_center = TRUE,
    scaling = as.character(job$preprocessing$scaling)
  ),
  sample_names = sample_names,
  classes = classes,
  class_levels = class_levels,
  component_names = current_model$component_names,
  hotelling_t2 = list(
    dimensions = hotelling_dimensions,
    formula = "p*(n-1)/(n-p)*F(confidence,p,n-p)",
    limits = list(
      `0.95` = hotelling_limit(0.95),
      `0.99` = hotelling_limit(0.99)
    )
  ),
  explained_variance = current_model$explained_variance,
  cumulative_variance = current_model$cumulative_variance,
  scores = current_model$scores,
  ppm = ppm_model,
  feature_ids = feature_ids_model,
  feature_axis = list(
    numeric = feature_axis_numeric,
    label = if (is.null(job$dataset$axis_label)) "Característica" else {
      as.character(job$dataset$axis_label)
    },
    representation = if (is.null(job$dataset$representation)) {
      "continuous_profile"
    } else as.character(job$dataset$representation),
    modality = if (is.null(job$dataset$modality)) "1H-NMR" else {
      as.character(job$dataset$modality)
    }
  ),
  loadings = current_model$loadings,
  standard_deviations = full_processed$sd,
  orthogonalization = orthogonalization,
  candidate_models = candidate_models,
  performance = list(
    strategy = switch(
      validation_strategy,
      random_subsets = "repeated_stratified_random_subsets",
      monte_carlo = "stratified_monte_carlo_holdout",
      leave_one_out = "leave_one_unit_out",
      venetian_blinds = "grouped_venetian_blinds"
    ),
    validation_method = validation_strategy,
    distance = "max.dist",
    repeats = repeats,
    data_splits = data_splits,
    submodels = length(validation_tasks),
    parallel_workers = parallel_workers,
    minimum_training_samples = expected_train_size,
    configured_train_fraction = if (validation_strategy == "monte_carlo") {
      train_fraction_requested
    } else NA_real_,
    train_fraction = 1 - mean(test_fractions),
    validation_fraction = mean(test_fractions),
    effective_validation_fraction = list(
      minimum = min(test_fractions), maximum = max(test_fractions),
      average = mean(test_fractions)
    ),
    validation_coverage = list(
      minimum_repetitions = min(validation_counts),
      maximum_repetitions = max(validation_counts),
      average_repetitions = mean(validation_counts),
      samples_never_validated = sum(validation_counts == 0L)
    ),
    resampling_unit = if (any(nzchar(biological_ids))) "biological_id_or_sample" else "sample",
    seed = validation_seed,
    components = seq_len(ncomp),
    mean_accuracy = colMeans(accuracy_matrix, na.rm = TRUE),
    sd_accuracy = apply(accuracy_matrix, 2, sd, na.rm = TRUE),
    mean_ber = mean_ber,
    sd_ber = sd_ber,
    se_ber = se_ber,
    calibration_accuracy = calibration_accuracy,
    calibration_ber = calibration_ber,
    calibration_correct = calibration_correct,
    calibration_auc_by_class = unname(calibration_auc),
    calibration_auc_macro = rowMeans(calibration_auc, na.rm = TRUE),
    cv_auc_by_class = unname(cv_auc),
    cv_auc_macro = rowMeans(cv_auc, na.rm = TRUE),
    r2x = cumsum(as.numeric(model$prop_expl_var$X)),
    r2y = r2y,
    q2y = 1 - q2y_press / q2y_tss,
    selection = list(
      criterion = "one_standard_error_on_mean_ber",
      minimum_error_component = minimum_component,
      suggested_component = suggested_component,
      current_component = current_component
    ),
    calibration = list(
      truth = classes,
      predicted = unname(as.matrix(full_prediction_result$class$max.dist)),
      decision_values = unname(full_prediction)
    ),
    confusion_matrices = confusion_output,
    repetitions = prediction_records
  )
)

write_json(result, args[[2]], auto_unbox = TRUE, digits = 15, pretty = FALSE, na = "null")

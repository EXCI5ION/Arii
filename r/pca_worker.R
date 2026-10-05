suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(mixOmics))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) {
  stop("Uso: pca_worker.R <job.json> <result.json>")
}

job_text <- paste(readLines(args[[1]], warn = FALSE, encoding = "UTF-8"), collapse = "\n")
job <- fromJSON(job_text, simplifyVector = TRUE)
input_path <- job$dataset$path

delimiter <- if (is.null(job$dataset$delimiter)) "," else as.character(job$dataset$delimiter)
raw <- read.table(
  input_path,
  header = TRUE,
  sep = delimiter,
  check.names = FALSE,
  stringsAsFactors = FALSE,
  quote = "\"",
  comment.char = ""
)

if (ncol(raw) < 2 || nrow(raw) < 2) {
  stop("El dataset no contiene suficientes muestras o variables")
}

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
rownames(X) <- sample_names

selected <- as.integer(job$selected_sample_indices) + 1L
if (length(selected) < 3) stop("PCA requiere al menos tres muestras")
if (any(selected < 1L | selected > nrow(X))) stop("Índice de muestra inválido")

X <- X[selected, , drop = FALSE]
sample_names <- sample_names[selected]
classes <- as.character(job$classes[selected])
X_selected_raw <- X

means <- colMeans(X)
standard_deviations <- apply(X, 2, sd)
valid <- is.finite(standard_deviations) & standard_deviations > .Machine$double.eps
if (!all(valid)) {
  X <- X[, valid, drop = FALSE]
  ppm <- ppm[valid]
  feature_ids <- feature_ids[valid]
  means <- means[valid]
  standard_deviations <- standard_deviations[valid]
}

X <- sweep(X, 2, means, "-")
if (identical(job$preprocessing$scaling, "pareto")) {
  X <- sweep(X, 2, sqrt(standard_deviations), "/")
} else if (identical(job$preprocessing$scaling, "unit_variance")) {
  X <- sweep(X, 2, standard_deviations, "/")
}

requested_components <- as.integer(job$n_components)
maximum_components <- min(nrow(X) - 1L, ncol(X))
ncomp <- min(requested_components, maximum_components)
model <- mixOmics::pca(X, ncomp = ncomp, center = FALSE, scale = FALSE)

fit_rmse <- numeric(ncomp)
fit_r2x <- numeric(ncomp)
fit_total_sum_squares <- sum(X ^ 2)
for (component_index in seq_len(ncomp)) {
  fit_loadings <- model$loadings$X[, seq_len(component_index), drop = FALSE]
  fit_scores <- model$variates$X[, seq_len(component_index), drop = FALSE]
  fit_residual <- X - fit_scores %*% t(fit_loadings)
  fit_residual_sum_squares <- sum(fit_residual ^ 2)
  fit_rmse[component_index] <- sqrt(mean(fit_residual ^ 2))
  fit_r2x[component_index] <- if (fit_total_sum_squares > 0) {
    1 - fit_residual_sum_squares / fit_total_sum_squares
  } else {
    NA_real_
  }
}

validation_result <- NULL
if (!is.null(job$validation) && isTRUE(job$validation$enabled)) {
  repeats <- as.integer(job$validation$repeats)
  train_fraction <- as.numeric(job$validation$train_fraction)
  validation_seed <- as.integer(job$validation$seed)
  if (repeats < 1L) stop("El número de repeticiones debe ser positivo")
  if (train_fraction <= 0 || train_fraction >= 1) stop("train_fraction debe estar entre 0 y 1")
  set.seed(validation_seed)
  rmse_matrix <- matrix(NA_real_, nrow = repeats, ncol = ncomp)
  q2x_matrix <- matrix(NA_real_, nrow = repeats, ncol = ncomp)
  split_records <- vector("list", repeats)

  for (repeat_index in seq_len(repeats)) {
    train_indices <- integer(0)
    for (class_name in unique(classes)) {
      group_indices <- which(classes == class_name)
      if (length(group_indices) == 1L) {
        group_train <- group_indices
      } else {
        group_train_count <- round(length(group_indices) * train_fraction)
        group_train_count <- max(1L, min(length(group_indices) - 1L, group_train_count))
        group_train <- sample(group_indices, group_train_count, replace = FALSE)
      }
      train_indices <- c(train_indices, group_train)
    }
    train_indices <- sort(unique(train_indices))
    test_indices <- setdiff(seq_len(nrow(X_selected_raw)), train_indices)
    if (length(test_indices) < 1L) stop("La partición no produjo muestras de validación")

    X_train <- X_selected_raw[train_indices, , drop = FALSE]
    X_test <- X_selected_raw[test_indices, , drop = FALSE]
    fold_means <- colMeans(X_train)
    fold_sd <- apply(X_train, 2, sd)
    fold_valid <- is.finite(fold_sd) & fold_sd > .Machine$double.eps
    X_train <- sweep(X_train[, fold_valid, drop = FALSE], 2, fold_means[fold_valid], "-")
    X_test <- sweep(X_test[, fold_valid, drop = FALSE], 2, fold_means[fold_valid], "-")
    if (identical(job$preprocessing$scaling, "pareto")) {
      divisor <- sqrt(fold_sd[fold_valid])
      X_train <- sweep(X_train, 2, divisor, "/")
      X_test <- sweep(X_test, 2, divisor, "/")
    } else if (identical(job$preprocessing$scaling, "unit_variance")) {
      divisor <- fold_sd[fold_valid]
      X_train <- sweep(X_train, 2, divisor, "/")
      X_test <- sweep(X_test, 2, divisor, "/")
    }

    fold_ncomp <- min(ncomp, nrow(X_train) - 1L, ncol(X_train))
    fold_model <- mixOmics::pca(
      X_train, ncomp = fold_ncomp, center = FALSE, scale = FALSE
    )
    baseline_sum_squares <- sum(X_test ^ 2)
    for (component_index in seq_len(fold_ncomp)) {
      fold_loadings <- fold_model$loadings$X[, seq_len(component_index), drop = FALSE]
      test_scores <- X_test %*% fold_loadings
      reconstruction <- test_scores %*% t(fold_loadings)
      residual <- X_test - reconstruction
      press <- sum(residual ^ 2)
      rmse_matrix[repeat_index, component_index] <- sqrt(mean(residual ^ 2))
      q2x_matrix[repeat_index, component_index] <- if (baseline_sum_squares > 0) {
        1 - press / baseline_sum_squares
      } else {
        NA_real_
      }
    }
    split_records[[repeat_index]] <- list(
      `repeat` = repeat_index,
      train_samples = sample_names[train_indices],
      validation_samples = sample_names[test_indices],
      rmse = unname(rmse_matrix[repeat_index, ]),
      q2x = unname(q2x_matrix[repeat_index, ])
    )
  }

  validation_result <- list(
    strategy = "repeated_stratified_random_subsets",
    repeats = repeats,
    train_fraction = train_fraction,
    seed = validation_seed,
    preprocessing_scope = "fit_on_training_only",
    components = seq_len(ncomp),
    mean_rmse = colMeans(rmse_matrix, na.rm = TRUE),
    sd_rmse = apply(rmse_matrix, 2, sd, na.rm = TRUE),
    mean_q2x = colMeans(q2x_matrix, na.rm = TRUE),
    sd_q2x = apply(q2x_matrix, 2, sd, na.rm = TRUE),
    repetitions = split_records
  )
}

# Límite clásico T² para una proyección bidimensional:
# T²(alpha) = p(n-1)/(n-p) * F(alpha; p, n-p), con p = 2.
hotelling_dimensions <- 2L
hotelling_limit <- function(confidence) {
  hotelling_dimensions * (nrow(X) - 1) / (nrow(X) - hotelling_dimensions) *
    qf(confidence, hotelling_dimensions, nrow(X) - hotelling_dimensions)
}

result <- list(
  schema_version = "1.0",
  method = "pca",
  engine = list(
    name = "mixOmics",
    version = as.character(packageVersion("mixOmics")),
    r_version = R.version.string
  ),
  dimensions = list(
    samples = nrow(X),
    variables = ncol(X),
    removed_constant_variables = sum(!valid)
  ),
  preprocessing = list(
    mean_center = TRUE,
    scaling = as.character(job$preprocessing$scaling)
  ),
  sample_names = sample_names,
  classes = classes,
  component_names = colnames(model$variates$X),
  hotelling_t2 = list(
    dimensions = hotelling_dimensions,
    formula = "p*(n-1)/(n-p)*F(confidence,p,n-p)",
    limits = list(
      `0.95` = hotelling_limit(0.95),
      `0.99` = hotelling_limit(0.99)
    )
  ),
  explained_variance = as.numeric(model$prop_expl_var$X),
  cumulative_variance = as.numeric(model$cum.var),
  fit_metrics = list(
    components = seq_len(ncomp),
    rmse = fit_rmse,
    r2x = fit_r2x,
    scope = "full_model_reconstruction"
  ),
  scores = unname(model$variates$X),
  ppm = ppm,
  feature_ids = feature_ids,
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
  loadings = unname(model$loadings$X),
  standard_deviations = standard_deviations,
  validation = validation_result
)

write_json(
  result,
  path = args[[2]],
  auto_unbox = TRUE,
  digits = 15,
  pretty = FALSE,
  na = "null"
)

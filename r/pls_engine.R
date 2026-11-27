# Adapter between Arii's supervised-model contract and pls::simpls.fit.
#
# The statistical algorithm is provided by the published CRAN package `pls`.
# Arii supplies dummy-response encoding, cumulative predictions, classification,
# cross-validation, metrics, permutation tests and the optional OPLS rotation.

simpls_require_package <- function() {
  if (!requireNamespace("pls", quietly = TRUE)) {
    stop(
      "El motor SIMPLS requiere el paquete R 'pls'. Instale el runtime de ",
      "Arii que incluye pls o seleccione el motor mixOmics."
    )
  }
  invisible(TRUE)
}

simpls_fit <- function(X, Y, ncomp, scale_y = FALSE) {
  simpls_require_package()
  X <- as.matrix(X)
  Y <- as.matrix(Y)
  storage.mode(X) <- "double"
  storage.mode(Y) <- "double"
  if (nrow(X) != nrow(Y)) stop("X e Y deben tener el mismo número de filas")
  if (anyNA(X) || anyNA(Y) || any(!is.finite(X)) || any(!is.finite(Y))) {
    stop("SIMPLS requiere matrices finitas y sin valores ausentes")
  }
  if (isTRUE(scale_y)) {
    stop("El motor SIMPLS de Arii utiliza la matriz indicadora Y sin escalar")
  }

  requested <- as.integer(ncomp)
  maximum <- min(nrow(X) - 1L, ncol(X), requested)
  if (!is.finite(requested) || requested < 1L || maximum < 1L) {
    stop("El número de componentes no es válido")
  }

  fitted <- tryCatch(
    pls::simpls.fit(
      X, Y, ncomp = maximum, center = TRUE,
      stripped = FALSE, orthScores = FALSE
    ),
    error = function(condition) {
      stop("pls::simpls.fit no pudo ajustar el modelo: ", conditionMessage(condition))
    }
  )
  component_count <- dim(fitted$coefficients)[[3]]
  if (is.null(component_count) || component_count < 1L) {
    stop("pls::simpls.fit no pudo extraer ninguna componente")
  }

  scores <- as.matrix(fitted$scores[, seq_len(component_count), drop = FALSE])
  loadings <- as.matrix(fitted$loadings[, seq_len(component_count), drop = FALSE])
  centered_x <- sweep(X, 2, fitted$Xmeans, "-")
  total_x <- sum(centered_x ^ 2)
  explained_x <- vapply(seq_len(component_count), function(component) {
    contribution <- tcrossprod(scores[, component], loadings[, component])
    sum(contribution ^ 2) / total_x
  }, numeric(1))

  structure(list(
    fitted = fitted,
    coefficients = fitted$coefficients[, , seq_len(component_count), drop = FALSE],
    scores = scores,
    loadings = loadings,
    explained_variance_x = explained_x,
    x_center = as.numeric(fitted$Xmeans),
    y_center = as.numeric(fitted$Ymeans),
    ncomp = component_count,
    package_version = as.character(utils::packageVersion("pls"))
  ), class = "arii_pls_simpls")
}

simpls_predict_cube <- function(model, newdata) {
  X <- as.matrix(newdata)
  storage.mode(X) <- "double"
  if (ncol(X) != length(model$x_center)) {
    stop("newdata no tiene el mismo número de variables que el modelo")
  }
  centered <- sweep(X, 2, model$x_center, "-")
  output <- array(
    NA_real_, dim = c(nrow(centered), length(model$y_center), model$ncomp)
  )
  for (component in seq_len(model$ncomp)) {
    prediction <- centered %*% model$coefficients[, , component]
    output[, , component] <- sweep(prediction, 2, model$y_center, "+")
  }
  output
}

simpls_indicator_matrix <- function(response, levels) {
  output <- 1 * outer(response, levels, "==")
  colnames(output) <- levels
  output
}

simpls_fit_predict_cube <- function(train, response, test, levels, ncomp) {
  model <- simpls_fit(
    train,
    simpls_indicator_matrix(response, levels),
    ncomp = ncomp,
    scale_y = FALSE
  )
  simpls_predict_cube(model, test)
}

simpls_classify_cube <- function(cube, levels) {
  dimensions <- dim(cube)
  output <- matrix(NA_character_, dimensions[[1]], dimensions[[3]])
  for (component in seq_len(dimensions[[3]])) {
    decisions <- matrix(
      cube[, , component], nrow = dimensions[[1]], ncol = dimensions[[2]]
    )
    output[, component] <- vapply(seq_len(nrow(decisions)), function(row_index) {
      row <- decisions[row_index, ]
      if (!any(is.finite(row))) stop("SIMPLS produjo una respuesta no estimable")
      row[!is.finite(row)] <- -Inf
      levels[[which.max(row)]]
    }, character(1))
  }
  output
}

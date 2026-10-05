suppressPackageStartupMessages(library(jsonlite))

packages <- c("mixOmics", "jsonlite")
package_info <- lapply(packages, function(package_name) {
  installed <- requireNamespace(package_name, quietly = TRUE)
  list(
    name = package_name,
    installed = installed,
    version = if (installed) as.character(packageVersion(package_name)) else NA_character_
  )
})

result <- list(
  status = "ok",
  r_version = R.version.string,
  packages = package_info
)

cat(toJSON(result, auto_unbox = TRUE, pretty = TRUE))

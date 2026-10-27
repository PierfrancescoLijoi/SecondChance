terraform {
  required_version = ">= 1.16"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.81" }
    azuread = { source = "hashicorp/azuread", version = "~> 3.10" }
    time    = { source = "hashicorp/time", version = "~> 0.13" }
  }
}

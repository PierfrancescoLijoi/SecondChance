# The demo environment as scripts/azure/deploy.sh applies it, evaluated offline with the module's mocked providers.

mock_provider "azurerm" {
  source = "../../modules/secondchance/tests/mocks/azurerm"
}

mock_provider "azuread" {
  mock_data "azuread_client_config" {
    defaults = {
      tenant_id = "11111111-2222-3333-4444-555555555555"
      object_id = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
      client_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  }
  mock_data "azuread_application_published_app_ids" {
    defaults = {
      result = { MicrosoftGraph = "00000003-0000-0000-c000-000000000000" }
    }
  }
  mock_resource "azuread_service_principal" {
    defaults = {
      object_id    = "cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee"
      app_role_ids = { "User.Read.All" = "df021288-bdef-4463-88db-98f22de89214" }
    }
  }
  mock_resource "azuread_application" {
    defaults = {
      client_id = "dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
      id        = "/applications/dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  }
}

mock_provider "time" {}

variables {
  subscription_id = "99999999-8888-7777-6666-555555555555"
  image_tag       = "abc123"
  alarm_email     = "ops@example.org"
}

run "the_demo_is_small_ephemeral_and_unprotected" {
  command = apply

  assert {
    condition     = module.secondchance.resource_group == "rg-secondchance-demo"
    error_message = "One resource group holds the whole demo, so destroying it leaves nothing behind."
  }
  assert {
    condition     = length(module.secondchance.jobs) == 8 && contains(keys(module.secondchance.jobs), "seed")
    error_message = "The demo bootstraps, migrates, seeds, pings, checks, smoke-tests and runs both maintenance jobs."
  }
  assert {
    condition     = module.secondchance.database_connection_budget.peak <= 40
    error_message = "The burstable database is the smallest tier: the replica ceilings must fit it."
  }
}

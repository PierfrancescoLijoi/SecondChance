# The pilot environment, evaluated offline with the module's mocked providers.

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

run "the_pilot_is_protected_and_has_no_synthetic_data" {
  command = apply

  assert {
    condition     = module.secondchance.resource_group == "rg-secondchance-pilot"
    error_message = "The pilot lives in its own resource group."
  }
  assert {
    condition     = !contains(keys(module.secondchance.jobs), "seed") && !contains(keys(module.secondchance.jobs), "tools")
    error_message = "Synthetic data never reaches the pilot."
  }
  assert {
    condition     = module.secondchance.schedules.requeue == "*/2 * * * *"
    error_message = "The pilot recovers lost work every two minutes (ADR-010)."
  }
}

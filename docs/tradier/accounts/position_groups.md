Get Account Position Groups

# Get Account Position Groups

Retrieves all position groups for a specific account.

# OpenAPI definition

```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "Tradier Brokerage API",
    "description": "API for accessing Tradier brokerage services",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "https://api.tradier.com",
      "description": "Production server"
    },
    {
      "url": "https://sandbox.tradier.com",
      "description": "Sandbox environment for testing"
    }
  ],
  "paths": {
    "/v1/accounts/{account_id}/position-groups": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account Position Groups",
        "description": "Retrieves all position groups for a specific account.",
        "operationId": "brokerage-api-accounts-get-account-position-groups",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AccountIdParam"
          },
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "responses": {
          "200": {
            "description": "Position groups information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/PositionGroupsResponse"
                },
                "example": {
                  "position-groups": [
                    {
                      "id": 1,
                      "label": "TROW Covered Call",
                      "symbols": [
                        "TROW",
                        "TROW260116C00125000"
                      ]
                    },
                    {
                      "id": 2,
                      "label": "Degen Put Strategy",
                      "symbols": [
                        "ETHA251219C00026000",
                        "ETHA251219P00025000"
                      ]
                    }
                  ]
                }
              }
            }
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
          },
          "403": {
            "$ref": "#/components/responses/Forbidden"
          },
          "404": {
            "$ref": "#/components/responses/NotFound"
          }
        }
      }
    }
  },
  "components": {
    "parameters": {
      "AcceptHeader": {
        "name": "Accept",
        "in": "header",
        "required": true,
        "schema": {
          "type": "string",
          "enum": [
            "application/json"
          ]
        },
        "description": "Response format"
      },
      "AccountIdParam": {
        "name": "account_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string"
        },
        "description": "ID of the account",
        "example": "VA000001"
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "Forbidden": {
        "description": "Access denied to the requested resource"
      },
      "NotFound": {
        "description": "The requested resource was not found"
      }
    },
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Bearer <access_token>",
        "description": "Authentication using Bearer token"
      }
    },
    "schemas": {
      "PositionGroupsResponse": {
        "type": "object",
        "properties": {
          "position-groups": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/PositionGroupSummary"
            },
            "description": "List of position groups"
          }
        }
      },
      "PositionGroupSummary": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer",
            "description": "The position group ID"
          },
          "label": {
            "type": "string",
            "description": "The position group name"
          },
          "symbols": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "List of symbols in the position group"
          }
        }
      }
    }
  }
}
```
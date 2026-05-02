Update Position Group

# Update Position Group

Updates an existing position group for a specific account.

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
    "/v1/accounts/{account_id}/position-groups/{position_group_id}": {
      "put": {
        "tags": [
          "Accounts"
        ],
        "summary": "Update Position Group",
        "description": "Updates an existing position group for a specific account.",
        "operationId": "brokerage-api-accounts-put-account-position-groups",
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
            "$ref": "#/components/parameters/PositionGroupIdParam"
          },
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/x-www-form-urlencoded": {
              "schema": {
                "type": "object",
                "required": [
                  "label",
                  "symbols"
                ],
                "properties": {
                  "label": {
                    "type": "string",
                    "description": "A position group name"
                  },
                  "symbols": {
                    "type": "string",
                    "description": "Comma-delimited list of symbols to add to the position group"
                  }
                }
              },
              "example": {
                "label": "Medical Plays Updated",
                "symbols": "MRK"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Position group updated successfully",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/PositionGroupResponse"
                },
                "example": {
                  "position-group": {
                    "id": 2,
                    "label": "Medical Plays Updated",
                    "symbols": [
                      "UNH",
                      "PFE",
                      "JNJ",
                      "MRK"
                    ]
                  }
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
      },
      "PositionGroupIdParam": {
        "name": "position_group_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "integer"
        },
        "description": "The position group ID"
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
      "PositionGroupResponse": {
        "type": "object",
        "properties": {
          "position-group": {
            "$ref": "#/components/schemas/PositionGroup"
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
      },
      "PositionGroup": {
        "allOf": [
          {
            "$ref": "#/components/schemas/PositionGroupSummary"
          },
          {
            "type": "object",
            "properties": {
              "items": {
                "type": "object",
                "properties": {
                  "item": {
                    "type": "array",
                    "items": {
                      "$ref": "#/components/schemas/PositionGroupItem"
                    },
                    "description": "List of symbols in the position group"
                  }
                }
              }
            }
          }
        ]
      },
      "PositionGroupItem": {
        "type": "object",
        "properties": {
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          },
          "id": {
            "type": "string",
            "description": "The symbol ID (lowercase)"
          }
        }
      }
    }
  }
}
```
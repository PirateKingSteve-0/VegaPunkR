Get Options Expirations

# Get Options Expirations

Get available expiration dates for a specific underlying symbol

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
    "/v1/markets/options/expirations": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Options Expirations",
        "description": "Get available expiration dates for a specific underlying symbol",
        "operationId": "brokerage-api-markets-get-options-expirations",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AcceptHeader"
          },
          {
            "name": "symbol",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "The underlying security symbol",
            "example": "AAPL"
          },
          {
            "name": "includeAllRoots",
            "in": "query",
            "required": true,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include all option roots"
          },
          {
            "name": "strikes",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include strikes in response"
          },
          {
            "name": "contractSize",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include contract size in response"
          },
          {
            "name": "expirationType",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include expiration type in response"
          }
        ],
        "responses": {
          "200": {
            "description": "Available expiration dates",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ExpirationsResponse"
                },
                "example": {
                  "expirations": {
                    "date": [
                      "2021-02-05",
                      "2021-02-12",
                      "2021-02-19",
                      "2021-02-26",
                      "2021-03-19",
                      "2021-04-16",
                      "2021-06-18",
                      "2021-09-17",
                      "2022-01-21",
                      "2022-06-17",
                      "2023-01-20"
                    ]
                  }
                }
              }
            }
          },
          "400": {
            "$ref": "#/components/responses/BadRequest"
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
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
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "BadRequest": {
        "description": "Invalid request parameters or body"
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
      "ExpirationsResponse": {
        "type": "object",
        "properties": {
          "expirations": {
            "type": "object",
            "properties": {
              "date": {
                "type": "array",
                "items": {
                  "type": "string",
                  "format": "date"
                },
                "description": "List of available expiration dates"
              },
              "strikes": {
                "type": "object",
                "properties": {
                  "strike": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "date": {
                          "type": "string",
                          "format": "date"
                        },
                        "strike": {
                          "type": "array",
                          "items": {
                            "type": "number",
                            "format": "float"
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```
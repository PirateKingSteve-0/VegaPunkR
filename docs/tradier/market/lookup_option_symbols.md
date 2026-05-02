Get Lookup Options Symbols

# Get Lookup Options Symbols

Get all options symbols for the given underlying. This will include additional option roots (ex. SPXW, RUTW) if applicable.

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
    "/v1/markets/options/lookup": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Lookup Options Symbols",
        "description": "Get all options symbols for the given underlying. This will include additional option roots (ex. SPXW, RUTW) if applicable.",
        "operationId": "brokerage-api-markets-get-lookup-options-symbols",
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
            "name": "underlying",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "The underlying security symbol",
            "example": "AAPL"
          }
        ],
        "responses": {
          "200": {
            "description": "Option symbols information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/OptionsLookupResponse"
                },
                "example": {
                  "options": {
                    "option": [
                      {
                        "symbol": "AAPL210416C00125000",
                        "rootsymbol": "AAPL",
                        "strike": 125,
                        "date": "2021-04-16",
                        "type": "call",
                        "description": "AAPL Apr 16 2021 $125.00 Call"
                      }
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
      "OptionsLookupResponse": {
        "type": "object",
        "properties": {
          "options": {
            "type": "object",
            "properties": {
              "option": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "symbol": {
                      "type": "string",
                      "description": "The option symbol"
                    },
                    "rootsymbol": {
                      "type": "string",
                      "description": "The root symbol"
                    },
                    "strike": {
                      "type": "number",
                      "format": "float",
                      "description": "The strike price"
                    },
                    "date": {
                      "type": "string",
                      "format": "date",
                      "description": "The expiration date"
                    },
                    "type": {
                      "type": "string",
                      "enum": [
                        "call",
                        "put"
                      ],
                      "description": "The option type"
                    },
                    "description": {
                      "type": "string",
                      "description": "The option description"
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
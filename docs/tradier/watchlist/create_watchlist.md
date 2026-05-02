Create Watchlist

# Create Watchlist

Create a new watchlist. The new watchlist created will use the specified name and optional symbols upon creation.

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
    "/v1/watchlists": {
      "post": {
        "tags": [
          "Watchlists"
        ],
        "summary": "Create Watchlist",
        "description": "Create a new watchlist. The new watchlist created will use the specified name and optional symbols upon creation.",
        "operationId": "brokerage-api-watchlists-create-watchlist",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/ContentTypeHeader"
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
                  "name",
                  "symbols"
                ],
                "properties": {
                  "name": {
                    "type": "string",
                    "description": "A watchlist name"
                  },
                  "symbols": {
                    "type": "string",
                    "description": "Comma-delimited list of symbols to add to watchlist"
                  }
                }
              },
              "example": {
                "name": "My Watchlist",
                "symbols": "AAPL,IBM,NFLX"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Watchlist created successfully",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WatchlistResponse"
                },
                "example": {
                  "watchlist": {
                    "name": "My Watchlist",
                    "id": "my_watchlist",
                    "public_id": "public-6f8f625wti",
                    "items": {
                      "item": [
                        {
                          "symbol": "AAPL",
                          "id": "aapl"
                        },
                        {
                          "symbol": "IBM",
                          "id": "ibm"
                        },
                        {
                          "symbol": "NFLX",
                          "id": "nflx"
                        }
                      ]
                    }
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
      },
      "ContentTypeHeader": {
        "name": "Content-Type",
        "in": "header",
        "required": true,
        "schema": {
          "type": "string",
          "enum": [
            "application/x-www-form-urlencoded"
          ]
        },
        "description": "Request content type"
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
      "WatchlistResponse": {
        "type": "object",
        "properties": {
          "watchlist": {
            "$ref": "#/components/schemas/Watchlist"
          }
        }
      },
      "WatchlistSummary": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "The watchlist name"
          },
          "id": {
            "type": "string",
            "description": "The watchlist ID"
          },
          "public_id": {
            "type": "string",
            "description": "The public ID of the watchlist"
          }
        }
      },
      "Watchlist": {
        "allOf": [
          {
            "$ref": "#/components/schemas/WatchlistSummary"
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
                      "$ref": "#/components/schemas/WatchlistItem"
                    },
                    "description": "List of symbols in the watchlist"
                  }
                }
              }
            }
          }
        ]
      },
      "WatchlistItem": {
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
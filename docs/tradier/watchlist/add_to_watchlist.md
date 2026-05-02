Add Symbols to Watchlist

# Add Symbols to Watchlist

Add symbols to an existing watchlist. If the symbol exists, it will be over-written.

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
    "/v1/watchlists/{watchlist_id}/symbols": {
      "post": {
        "tags": [
          "Watchlists"
        ],
        "summary": "Add Symbols to Watchlist",
        "description": "Add symbols to an existing watchlist. If the symbol exists, it will be over-written.",
        "operationId": "brokerage-api-watchlists-add-watchlist-symbols",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/WatchlistIdParam"
          },
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
                  "symbols"
                ],
                "properties": {
                  "symbols": {
                    "type": "string",
                    "description": "Comma-delimited list of symbols to add to watchlist"
                  }
                }
              },
              "example": {
                "symbols": "AAPL,IBM,NFLX,SPY"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Symbols added successfully",
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
                        },
                        {
                          "symbol": "SPY",
                          "id": "spy"
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
      },
      "WatchlistIdParam": {
        "name": "watchlist_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string"
        },
        "description": "ID of the watchlist",
        "example": "my_watchlist"
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "NotFound": {
        "description": "The requested resource was not found"
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
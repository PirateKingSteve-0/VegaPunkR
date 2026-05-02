Get Time & Sales

# Get Time & Sales

Time and Sales (timesales) is typically used for charting purposes. It captures pricing across a time slice at predefined intervals. Tick data is also available through this endpoint. This results in a very large data set for high-volume symbols, so the time slice needs to be much smaller to keep downloads time reasonable.

The amount of data depends on the granularity you are looking for with longer time intervals giving more depth in time and the shortest time intervals, ticks, giving the least depth.

<br />

| Interval | Data Available (Open) | Data Available (All) |
| -------- | --------------------- | -------------------- |
| tick     | 5 Days                | N/A                  |
| 1min     | 20 Days               | 10 Days              |
| 5min     | 40 Days               | 18 Days              |
| 15min    | 40 Dyas               | 18 Days              |

<br />

(Please note, tick data is not available in the sandbox environment)

There is a known issue as it pertains to downloading data using the tick interval from this endpoint as it results in extremely large datasets. Because of this, it is not recommended to get large sets of tick data via request/response, and instead use the streaming endpoints.

<br />

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
    "/v1/markets/timesales": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Time & Sales",
        "description": "Time and Sales (timesales) is typically used for charting purposes. It captures pricing across a time slice at predefined intervals. Tick data is also available through this endpoint. This results in a very large data set for high-volume symbols, so the time slice needs to be much smaller to keep downloads time reasonable.",
        "operationId": "brokerage-api-markets-get-timesales",
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
            "description": "The security symbol",
            "example": "AAPL"
          },
          {
            "name": "interval",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "tick",
                "1min",
                "5min",
                "15min"
              ],
              "default": "tick"
            },
            "description": "The interval for the data"
          },
          {
            "name": "start",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "format": "date-time"
            },
            "description": "The start date/time for the data (YYYY-MM-DD HH:MM)",
            "example": "2021-02-01 09:30"
          },
          {
            "name": "end",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "format": "date-time"
            },
            "description": "The end date/time for the data (YYYY-MM-DD HH:MM)",
            "example": "2021-02-01 16:00"
          },
          {
            "name": "session_filter",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "open",
                "all"
              ],
              "default": "all"
            },
            "description": "Filter pre/post market data"
          }
        ],
        "responses": {
          "200": {
            "description": "Time and sales data",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/TimeSalesResponse"
                },
                "example": {
                  "series": {
                    "data": [
                      {
                        "time": "2021-02-01 09:30:00",
                        "price": 132.04,
                        "open": 132.04,
                        "high": 132.15,
                        "low": 131.95,
                        "close": 132.05,
                        "volume": 1234567
                      },
                      {
                        "time": "2021-02-01 09:31:00",
                        "price": 132.12,
                        "open": 132.05,
                        "high": 132.2,
                        "low": 132,
                        "close": 132.12,
                        "volume": 987654
                      }
                    ],
                    "symbol": "AAPL"
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
      "TimeSalesResponse": {
        "type": "object",
        "properties": {
          "series": {
            "type": "object",
            "properties": {
              "data": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "time": {
                      "type": "string",
                      "format": "date-time",
                      "description": "The time"
                    },
                    "price": {
                      "type": "number",
                      "format": "float",
                      "description": "The price"
                    },
                    "open": {
                      "type": "number",
                      "format": "float",
                      "description": "The opening price"
                    },
                    "high": {
                      "type": "number",
                      "format": "float",
                      "description": "The high price"
                    },
                    "low": {
                      "type": "number",
                      "format": "float",
                      "description": "The low price"
                    },
                    "close": {
                      "type": "number",
                      "format": "float",
                      "description": "The closing price"
                    },
                    "volume": {
                      "type": "integer",
                      "description": "The trading volume"
                    }
                  }
                }
              },
              "symbol": {
                "type": "string",
                "description": "The security symbol"
              }
            }
          }
        }
      }
    }
  }
}
```
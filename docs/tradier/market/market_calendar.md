Get Market Calendar

# Get Market Calendar

Get the market calendar for current or a specific month

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
    "/v1/markets/calendar": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Market Calendar",
        "description": "Get the market calendar for current or a specific month",
        "operationId": "brokerage-api-markets-get-calendar",
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
            "name": "month",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "minimum": 1,
              "maximum": 12
            },
            "description": "The calendar month (1-12)",
            "example": 2
          },
          {
            "name": "year",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "minimum": 2000,
              "maximum": 2050
            },
            "description": "The calendar year",
            "example": 2021
          }
        ],
        "responses": {
          "200": {
            "description": "Market calendar",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/CalendarResponse"
                },
                "example": {
                  "calendar": {
                    "days": {
                      "day": [
                        {
                          "date": "2021-02-01",
                          "status": "open",
                          "description": "Market is open",
                          "premarket": {
                            "start": "04:00",
                            "end": "09:30"
                          },
                          "open": {
                            "start": "09:30",
                            "end": "16:00"
                          },
                          "postmarket": {
                            "start": "16:00",
                            "end": "20:00"
                          }
                        },
                        {
                          "date": "2021-02-06",
                          "status": "closed",
                          "description": "Market is closed"
                        }
                      ]
                    },
                    "month": 2,
                    "year": 2021
                  }
                }
              }
            }
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
      "CalendarResponse": {
        "type": "object",
        "properties": {
          "calendar": {
            "type": "object",
            "properties": {
              "days": {
                "type": "object",
                "properties": {
                  "day": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "date": {
                          "type": "string",
                          "format": "date",
                          "description": "The date"
                        },
                        "status": {
                          "type": "string",
                          "enum": [
                            "open",
                            "closed"
                          ],
                          "description": "The market status"
                        },
                        "description": {
                          "type": "string",
                          "description": "Description of the market status"
                        },
                        "premarket": {
                          "type": "object",
                          "properties": {
                            "start": {
                              "type": "string",
                              "format": "time",
                              "description": "Start time of pre-market trading"
                            },
                            "end": {
                              "type": "string",
                              "format": "time",
                              "description": "End time of pre-market trading"
                            }
                          }
                        },
                        "open": {
                          "type": "object",
                          "properties": {
                            "start": {
                              "type": "string",
                              "format": "time",
                              "description": "Start time of regular trading"
                            },
                            "end": {
                              "type": "string",
                              "format": "time",
                              "description": "End time of regular trading"
                            }
                          }
                        },
                        "postmarket": {
                          "type": "object",
                          "properties": {
                            "start": {
                              "type": "string",
                              "format": "time",
                              "description": "Start time of post-market trading"
                            },
                            "end": {
                              "type": "string",
                              "format": "time",
                              "description": "End time of post-market trading"
                            }
                          }
                        }
                      }
                    }
                  }
                }
              },
              "month": {
                "type": "integer",
                "description": "The calendar month"
              },
              "year": {
                "type": "integer",
                "description": "The calendar year"
              }
            }
          }
        }
      }
    }
  }
}
```
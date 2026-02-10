from pydantic import BaseModel, Field

class SearchQuerySchema(BaseModel):
    query: str = Field(..., description="The search term to look up")
    limit: int = Field(default=5, description="Maximum number of results to return")

class ChartGenerationSchema(BaseModel):
    data: list = Field(..., description="The data points to visualize")
    chart_type: str = Field(..., description="The visualization style")

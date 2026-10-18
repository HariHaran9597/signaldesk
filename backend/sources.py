from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    topic: str
    website: str
    kind: str = "rss"


SOURCES = (
    Source("huggingface", "Hugging Face", "https://huggingface.co/blog/feed.xml", "models", "https://huggingface.co/blog"),
    Source("hf-trending", "Hugging Face model discovery", "https://huggingface.co/api/models?pipeline_tag=text-generation&sort=downloads&direction=-1&limit=40&full=true&cardData=true", "models", "https://huggingface.co/models?pipeline_tag=text-generation&sort=downloads", "hf_models"),
    Source("nvidia", "NVIDIA Developer", "https://developer.nvidia.com/blog/feed/", "gpu", "https://developer.nvidia.com/blog"),
    Source("mcp", "MCP Maintainers", "https://blog.modelcontextprotocol.io/index.xml", "agents", "https://blog.modelcontextprotocol.io"),
    Source("github-transformers", "Hugging Face Transformers releases", "https://api.github.com/repos/huggingface/transformers/releases?per_page=10", "models", "https://github.com/huggingface/transformers", "github_releases"),
    Source("github-llama-cpp", "llama.cpp releases", "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10", "gpu", "https://github.com/ggml-org/llama.cpp", "github_releases"),
    Source("github-mcp-python", "MCP Python SDK releases", "https://api.github.com/repos/modelcontextprotocol/python-sdk/releases?per_page=10", "agents", "https://github.com/modelcontextprotocol/python-sdk", "github_releases"),
)
TOPICS = {"models", "agents", "gpu"}

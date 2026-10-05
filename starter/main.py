"""
Customer Support AI Agent — Starter Code
==========================================
Your task is to complete this file by implementing all sections marked
with # TODO comments.

Reference the project instructions and rubric for guidance.
Work through each section yourself.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
import argparse, json
import os, asyncio, boto3, sys
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

# ── TODO 1 — App Initialisation ───────────────────────────────────────────────
# Create a BedrockAgentCoreApp instance.
# This registers the ASGI server for AgentCore deployment.
# There must be exactly one instance per deployment.
#
# Hint: app = BedrockAgentCoreApp()

# TODO: Create the BedrockAgentCoreApp instance
app = BedrockAgentCoreApp()


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── TODO 2 — Configuration ────────────────────────────────────────────────────
# Replace the placeholder strings with your actual AWS resource values.
# You collected these in the infrastructure setup section of the project instructions.
#
# GATEWAY_URL format: https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# This starter uses an unsigned MCP connection and therefore assumes the
# project Gateway is configured with the NONE authorizer.
# KB_ID       format: 10-character alphanumeric string from the KB console
# REGION:     your AWS region, e.g. "us-east-1"
# MEMORY_ID   format: shown in the AgentCore Memory console

GATEWAY_URL = "https://customer-support-gateway-aok8tpdjj9.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "1STTXXEJIB"          
REGION      = "us-east-1"     
MEMORY_ID   = "CustomerSupportMemory-hPDswKC8PU" 


# ── TODO 3 — Model and Clients ────────────────────────────────────────────────
# Create:
#   1. A BedrockModel using model_id "global.amazon.nova-2-lite-v1:0"
#   2. A MemoryClient with region_name=REGION
#   3. A boto3 client for the "bedrock-agent-runtime" service in REGION
#
# Hint: model = BedrockModel(model_id=model_id)

model_id = "global.amazon.nova-2-lite-v1:0"

# TODO: Create the BedrockModel instance
model = BedrockModel(model_id=model_id)

# TODO: Create the MemoryClient instance
memory_client = MemoryClient(region_name=REGION)

# TODO: Create the boto3 bedrock-agent-runtime client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)

SYSTEM_PROMPT = """You are an intelligent, helpful, and empathetic Customer Support Assistant.
You assist customers with order issues, product details, return policies, and loyalty discounts.
Always use available tools to retrieve accurate knowledge base context or compute exact pricing when needed."""


def _tool_call_callback(**event):
    tool_use = event.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse")
    if tool_use:
        print(f"Tool called: {tool_use.get('name', 'unknown')}")

# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict[str, str]:
    """Return a dict mapping strategy type to namespace template string."""
    try:
        strategies = mem_client.get_memory_strategies(memory_id) or []
        namespaces = {}

        for strategy in strategies:
            if not isinstance(strategy, dict):
                continue
            
            strat_type = strategy.get("type")
            if not strat_type:
                continue

            # Extract namespaceTemplates or namespaces, handling None.
            ns_templates = strategy.get("namespaceTemplates") or strategy.get("namespaces") or []
            if ns_templates and isinstance(ns_templates, list):
                namespaces[strat_type] = ns_templates[0]

        return namespaces

    except Exception as e:
        logger.error(f"Error fetching namespaces: {e}")
        return {}

# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────
class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(memory_client, memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        if not event.agent.messages:
            return

        last_message = event.agent.messages[-1]

        # 1. Check that the message is from the user, not a tool result.
        if last_message.get("role") != "user":
            return

        content = last_message.get("content", "")
        user_query = ""

        # 2. Extract the user's query text.
        if isinstance(content, str):
            user_query = content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    user_query += block["text"]
                elif isinstance(block, str):
                    user_query += block

        if not user_query.strip():
            return

        retrieved_memories = []

        # 3. Search memories for each strategy.
        for strat_type, ns_template in self.namespaces.items():
            try:
                formatted_ns = ns_template.format(actorId=self.actor_id)
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=formatted_ns,
                    query=user_query,
                    top_k=5,
                )
                for mem in memories or []:
                    if not isinstance(mem, dict):
                        continue

                    content = mem.get("content")
                    text = mem.get("text")
                    if not text and isinstance(content, dict):
                        text = content.get("text")
                    elif not text and isinstance(content, str):
                        text = content
                    if text:
                        retrieved_memories.append(f"[{strat_type}] {text}")
            except Exception as e:
                logger.error(f"Error retrieving memory for {strat_type}: {e}")

        # 4. Prepend memory context to the original message.
        if retrieved_memories:
            memories_text = "\n".join(retrieved_memories)
            augmented_content = f"Customer Context:\n{memories_text}\n\n{user_query}"

            if isinstance(last_message["content"], str):
                last_message["content"] = augmented_content
            elif isinstance(last_message["content"], list):
                last_message["content"] = [{"text": augmented_content}]

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        messages = event.agent.messages
        if not messages:
            return

        last_user_query = None
        last_assistant_response = None

        # Search backward for the latest user query and assistant response.
        for msg in reversed(messages):
            role = msg.get("role")
            content = msg.get("content", "")

            text_str = ""
            if isinstance(content, str):
                text_str = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_str += block["text"]
                    elif isinstance(block, str):
                        text_str += block

            if role == "assistant" and not last_assistant_response and text_str.strip():
                last_assistant_response = text_str
            elif role == "user" and not last_user_query and text_str.strip():
                # If the message includes memory context, keep only the query text.
                if "Customer Context:\n" in text_str and "\n\n" in text_str:
                    text_str = text_str.split("\n\n", 1)[1]
                last_user_query = text_str

            if last_user_query and last_assistant_response:
                break

        # Save the conversation using create_event.
        if last_user_query and last_assistant_response:
            try:
                self.memory_client.create_event(
                    memory_id=self.memory_id,
                    actor_id=self.actor_id,
                    session_id=self.session_id,
                    messages=[
                        (last_user_query, "USER"),
                        (last_assistant_response, "ASSISTANT"),
                    ],
                )
            except Exception as e:
                logger.error(f"Failed to create memory event: {e}")

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────
@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    # 1. Check whether KB_ID is missing or still a placeholder.
    if not KB_ID or KB_ID == "<kbid>":
        return "Knowledge base not configured."

    try:
        # 2. Call retrieve on the AWS Bedrock Runtime client.
        resp = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query}
        )
        
        # 3. Extract the results.
        results = resp.get("retrievalResults", [])
        if not results:
            return "No relevant information found in the knowledge base."

        # 4. Combine the retrieved text chunks.
        chunks = [
            r.get("content", {}).get("text", "") 
            for r in results 
            if r.get("content", {}).get("text")
        ]
        
        if not chunks:
            return "No relevant information found in the knowledge base."

        return "\n---\n".join(chunks)

    except Exception as e:
        logger.error(f"Knowledge Base retrieval failed: {e}")
        return f"Error querying Knowledge Base: {str(e)}"

# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────
@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    # 1. Build Python code to run in the Code Interpreter sandbox.
    code = f"""
import json
import math

loyalty_points = {loyalty_points}
tier = "{tier}"
order_total = {order_total}
product_category = "{product_category}"

earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

# Calculate points redemption: every 100 points gives $1 off, rounded down to a multiple of 500.
# The points discount is capped at 50% of the order total (order_total * 0.50 * 100).
max_points_allowed = int(order_total * 0.50 * 100)
usable_points = min(loyalty_points, max_points_allowed)
points_redeemed = (usable_points // 500) * 500
points_discount = points_redeemed / 100.0

# Calculate the remaining balance and tier discount.
subtotal_after_points = order_total - points_discount
tier_rate = tier_rates.get(tier, 0.0)
tier_discount = round(subtotal_after_points * tier_rate, 2)
tier_discount_pct = round(tier_rate * 100, 2)

final_total = round(subtotal_after_points - tier_discount, 2)
total_savings = round(points_discount + tier_discount, 2)

# Calculate points earned on the current purchase.
earn_rate = earn_rates.get(product_category.lower(), 1)
points_earned = int(final_total * earn_rate)
remaining_points = loyalty_points - points_redeemed + points_earned

result = {{
    "original_total": order_total,
    "points_redeemed": points_redeemed,
    "points_discount": points_discount,
    "tier": tier,
    "tier_discount": tier_discount,
    "tier_discount_pct": tier_discount_pct,
    "final_total": final_total,
    "total_savings": total_savings,
    "points_earned": points_earned,
    "remaining_points": remaining_points
}}

print(json.dumps(result))
"""

    try:
        # 2. Run the code in a Code Interpreter session.
        with code_session(REGION) as session:
            response = session.invoke(
                "executeCode",
                {
                    "code": code,
                    "language": "python",
                    "clearContext": True,
                },
            )
            
            # 3. Extract the program's JSON stdout from the execution envelope.
            for event in response.get("stream", []):
                if "result" in event:
                    execution_result = event["result"]
                    if not isinstance(execution_result, dict):
                        raise ValueError("Code Interpreter returned an invalid execution result.")
                    if execution_result.get("isError") is not False:
                        raise RuntimeError(f"Code Interpreter reported an execution error: {execution_result}")

                    structured_content = execution_result.get("structuredContent")
                    stdout = (
                        structured_content.get("stdout")
                        if isinstance(structured_content, dict)
                        else None
                    )
                    if not isinstance(stdout, str) or not stdout.strip():
                        content = execution_result.get("content", [])
                        text_blocks = [
                            block["text"]
                            for block in content
                            if isinstance(block, dict) and isinstance(block.get("text"), str)
                        ] if isinstance(content, list) else []
                        stdout = "\n".join(text_blocks)

                    if not stdout.strip():
                        raise ValueError("Code Interpreter returned no program output.")

                    calculation = json.loads(stdout)
                    required_numeric_fields = (
                        "points_redeemed",
                        "tier_discount_pct",
                        "final_total",
                        "remaining_points",
                    )
                    if not isinstance(calculation, dict) or any(
                        not isinstance(calculation.get(field), (int, float))
                        or isinstance(calculation.get(field), bool)
                        for field in required_numeric_fields
                    ):
                        raise ValueError("Code Interpreter output is missing required numeric calculation fields.")

                    return json.dumps(calculation)

            raise ValueError("No execution result returned from Code Interpreter.")

    except Exception as e:
        logger.warning(f"Code Interpreter execution or output parsing failed ({e}), using fallback calculation.")
        
        # 4. Use a fallback calculation if Code Interpreter is unavailable.
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_rate = tier_rates.get(tier, 0.0)
        tier_discount = round(order_total * tier_rate, 2)
        final_total = round(order_total - tier_discount, 2)

        fallback_result = {
            "fallback": True,
            "original_total": order_total,
            "points_redeemed": 0,
            "tier": tier,
            "tier_discount": tier_discount,
            "tier_discount_pct": round(tier_rate * 100, 2),
            "final_total": final_total,
            "remaining_points": loyalty_points,
            "total_savings": tier_discount,
            "message": "Calculated tier discount fallback due to Code Interpreter unavailability."
        }
        return json.dumps(fallback_result)


# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────
@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
        prompt      (str, required) — the customer's message
        customer_id (str, optional) — unique customer identifier
        session_id  (str, optional) — session identifier; generated if absent
    """
    try:
        # 1. Extract parameters from the payload.
        user_input = payload.get("prompt", "")
        actor_id = payload.get("customer_id", "default_customer")
        session_id = payload.get("session_id") or str(uuid.uuid4())

        # 2. Initialize MemoryHook.
        memory_hook = MemoryHook(
            actor_id=actor_id,
            session_id=session_id,
            memory_client=memory_client,
            memory_id=MEMORY_ID,
        )

        # 3. Initialize the AgentCore browser.
        agent_core_browser = AgentCoreBrowser(region=REGION)

        # 4. Build the initial list of local tools.
        tools = [
            search_knowledge_base,
            calculate_loyalty_discount,
            agent_core_browser.browser,
        ]

        # 5. Connect to the MCP Gateway and load remote tools.
        mcp_client = MCPClient(url=GATEWAY_URL, startup_timeout=10)
        try:
            try:
                gateway_tools = await mcp_client.load_tools()
                tools.extend(gateway_tools)
            except Exception:
                logger.exception("Failed to load MCP Gateway tools")

            # 6. Create and run the Strands agent.
            agent = Agent(
                model=model,
                system_prompt=SYSTEM_PROMPT,
                tools=tools,
                hooks=[memory_hook],
                callback_handler=_tool_call_callback,
            )

            response = await agent.invoke_async(user_input)
        finally:
            try:
                mcp_client.stop(None, None, None)
            except Exception:
                logger.exception("Failed to close MCP Gateway client")

        # 7. Extract and return the text from the first content block.
        if hasattr(response, "message") and isinstance(response.message, dict):
            content_blocks = response.message.get("content", [])
            for block in content_blocks:
                if isinstance(block, dict) and "text" in block:
                    return block["text"]
                elif isinstance(block, str):
                    return block

        return str(response)

    except Exception as e:
        logger.error(f"Error during agent execution: {e}")
        return f"An error occurred while processing your request: {str(e)}"


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        app.run()
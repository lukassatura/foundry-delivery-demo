"""Hosted agent entry point. Foundry calls it through the Responses protocol on port 8088."""

import asyncio
import logging

from azure.ai.agentserver.responses import CreateResponse, ResponseContext, ResponsesAgentServerHost, TextResponse

from analysis import analyse, render

logger = logging.getLogger("report-deviation-agent")
app = ResponsesAgentServerHost()


@app.response_handler
async def handle(request: CreateResponse, context: ResponseContext, _cancellation: asyncio.Event):
    text = await context.get_input_text() or ""
    result = await asyncio.to_thread(analyse, text)
    logger.info("Compared reports: %d deviations, error=%s", len(result.deviations), bool(result.error))
    return TextResponse(context, request, text=render(result))


if __name__ == "__main__":
    app.run()

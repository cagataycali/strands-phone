# Models

| `MODEL_PROVIDER` | Model | Rate on the line | Auth |
|---|---|---|---|
| `nova` | Amazon Nova 2 Sonic | 8 kHz in and out, no resampling | EC2 instance role |
| `openai` | OpenAI gpt-realtime-2 | 24 kHz, `Up3` / `Down3` in the bridge | `OPENAI_API_KEY` |

Credentials never expire: the role rotates itself and signs with SigV4, and the OpenAI key sits in a root-only file. Nova's role needs `bedrock:InvokeModel` on `InvokeModelWithBidirectionalStream`; OpenAI's key goes as `Authorization: Bearer`. Both models get the same tools and the same prompt. To switch, change one line in `.secrets.env` and run `deploy/deploy.sh` again.

<figure class="sr-draw" markdown>
![How each model is authorised on the host](assets/drawings/p04_auth.paper.svg){ .sr-draw--paper }
![](assets/drawings/p04_auth.dark.svg){ .sr-draw--dark }
</figure>

Measured over the phone network:

| | Nova 2 Sonic | gpt-realtime-2 |
|---|---|---|
| answered | 31 ms | 312 ms (websocket opens while ringing) |
| greeting audio after answer | 0.82 s | 0.62 s |
| tool call | yes | yes |

# How it works

<figure class="sr-draw" markdown>
![SIP ladder of one inbound call](assets/drawings/p02_one_call.paper.svg){ .sr-draw--paper }
![](assets/drawings/p02_one_call.dark.svg){ .sr-draw--dark }
</figure>

strands-phone is a small SIP user agent. Chime SDK Voice Connector handles the phone network. strands-phone speaks SIP over UDP for signalling and RTP with G.711 u-law for audio. On an incoming INVITE it replies 100 Trying, then 180 Ringing, then 200 OK. As `InboundCall` it answers calls; as `Call` it places them. The model connection opens while the line is still ringing, so the agent is ready the moment the call is picked up.

<figure class="sr-draw" markdown>
![The audio bridge: caller audio into the agent, agent audio paced onto the line](assets/drawings/p03_audio_bridge.paper.svg){ .sr-draw--paper }
![](assets/drawings/p03_audio_bridge.dark.svg){ .sr-draw--dark }
</figure>

Each RTP packet is decoded to PCM16 and becomes one `AudioDelta` sent to the agent. The agent's `bidi_audio_delta` events fill a playout buffer, and a 20 ms clock sends one frame per tick. When the buffer is empty, the clock sends a -60 dBFS noise floor instead of silence. When the caller interrupts, the model emits `bidi_barge_in` and the buffer is dropped, so the agent stops mid-word.

| File | |
|---|---|
| `strands_phone/sip.py` | parse, SDP, the datagram endpoint |
| `strands_phone/rtp.py`, `g711.py` | RTP PCMU, u-law identical to audioop bit for bit |
| `strands_phone/resample.py` | `Up3` / `Down3`, a 31-tap FIR for 24 kHz models |
| `strands_phone/call.py` | `Call`, `InboundCall`, the clock, barge-in, opt-in recording |
| `strands_phone/agent.py` | `make_model()`, `BidiAgent`, `current_time`, `hang_up` |

The tests include a loopback call: our `Call` dials our `InboundCall` over real SIP and RTP on localhost, and audio has to cross in both directions.

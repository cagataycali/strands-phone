# Design

<figure class="sr-draw" markdown>
![What runs where: Voice Connector, one EC2 host running strands-phone, the BidiAgent and the two models](assets/drawings/p05_design.paper.svg){ .sr-draw--paper }
![](assets/drawings/p05_design.dark.svg){ .sr-draw--dark }
</figure>

A SIP trunk carries audio in both directions. Chime SDK Voice Connector owns the number and the trunk. Origination sends incoming calls to the host, and termination accepts outgoing calls only from the host's Elastic IP. One EC2 host runs `strands-phone.service`: `InboundCall` answers, `Call` dials, and both bridge RTP to a `BidiAgent`.

## Choices

- **No SDK change.** The bridge sends one `agent.send(AudioDelta)` per RTP packet in, and feeds `agent.receive()` into a playout buffer on the way out.
- **The phone's own rate.** Nova 2 Sonic runs at 8 kHz in and out. Only 24 kHz models pay for `Up3` / `Down3`.
- **One call per process.** systemd restarts the listener after every call, so no state leaks from one call to the next.
- **Open the model while the phone rings.** The agent is ready the moment the call is answered.
- **Never digitally silent.** The model only answers while audio flows, so the clock sends a -60 dBFS noise floor whenever the buffer is empty.
- **Evidence for every call.** A stereo WAV plus a JSON timeline. Measure barge-in from the WAV.
- **No long-lived AWS secrets on the host.** Nova signs with the instance role. An OpenAI key stays in a root-only file.

## Next

1. Register a caller name (CNAM), so mobile carriers stop sending outbound calls to voicemail.
2. Measure barge-in from the WAV, with a target under 300 ms, using a scripted SIP test caller.
3. Hand a call to a human or a contact-centre queue.

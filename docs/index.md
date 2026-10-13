---
hide: [navigation, toc]
template_class: sr-home
title: strands-phone
---

# strands-phone

<div class="sr-hero" markdown>
<div markdown>
<p class="sr-hero__title">Call your <em>agent</em>.</p>
<p class="sr-hero__lead">A real phone number that rings a Strands <code>BidiAgent</code>. It listens and speaks at the same time, can be interrupted, calls tools and hangs up when you're done. It runs on Nova 2 Sonic or gpt-realtime-2.</p>
<div class="sr-hero__actions">
<a class="sr-btn sr-btn--primary" href="quickstart/">Quickstart</a>
<a class="sr-btn" href="how-it-works/">How it works</a>
</div>
</div>
<div markdown>
<figure class="sr-draw" markdown>
![A phone call flowing through the Chime SDK Voice Connector and strands-phone into a BidiAgent and back](assets/drawings/p01_call_path.paper.svg){ .sr-draw--paper }
![](assets/drawings/p01_call_path.dark.svg){ .sr-draw--dark }
</figure>
</div>
</div>

<div class="sr-pair" markdown>

```bash title="answer calls"
infra/up.sh        # number, Voice Connector, EC2, role
deploy/deploy.sh   # systemd: strands-phone answer
# now dial the number in .state.env
```

```bash title="place a call"
strands-phone call +15551234567
# the agent speaks first, then listens
```

```python title="the agent on the line"
BidiAgent(
    model=make_model(),  # nova | openai
    tools=[current_time, hang_up],
    system_prompt="You are on a real phone call...",
)
```

```yaml title="measured, first real call"
answered: 31 ms
first_audio: 0.82 s
reply_after_you: 0.13 to 0.68 s
tool_call: current_time
ended_by: hang_up
```

</div>

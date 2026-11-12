<div align="center">

# ✳ AI Station

### Your own AI. Made simple. No platform censorship.

**A familiar ChatGPT-style experience, on your own computer. No AI or IT background needed.**

Your conversations, images, videos, voices, music and agents — together, on your machine.

**Your models. Your rules. No cloud quotas or per-token fees for local generation.**

[Get started](#-get-started) · [Installation guide](https://ai-station.dev/install/) · [See it in action](#-one-station-many-ways-to-create) · [Help us test](#help-make-it-simple) · [Real hardware results](#-real-hardware-real-results) · [The vision](#-where-were-going)

`v0.5.0` · `Linux & Windows` · `Local inference` · `Cloud optional` · [Free for noncommercial use](LICENSE)

![AI Station product tour: conversation, video creation and the artifact Library](docs/media/station-tour.gif)

</div>

**Local AI should be for anyone with a capable computer.** You shouldn't need to
know what a model server is, use a terminal or understand GPUs to get started.
You bring the hardware. We're building an app that takes care of the setup.

Ask a question. Make an image or video. Create a voiceover or a soundtrack.
Put an agent to work. Keep your conversations, files and results in one familiar
workspace — powered by your own computer.

**The experience we're building:**

| ① Download | ② Install | ③ Create |
| --- | --- | --- |
| Get one app for your workstation. | Guided setup checks your hardware and offers models that fit. | Open the conversation and describe what you want. |

You should not have to learn how to run model servers, choose Python environments
or assemble separate AI tools. **Making local AI approachable is the product.**
The conversation is your starting point: describe what you want, and AI Station
coordinates the tools behind it. Dedicated workspaces are there when you want
more control.

The conversation uses a ReAct orchestrator: it chooses an
available tool, observes its actual result and can pass that result to the next
tool. Reference images survive follow-up questions, and an image result can become
the input of a recurring-agent draft for your review.
Existing image agents expose compatible installed models for Generate, Edit and
Recompose directly beside the image operation.
[Implementation and real qualification](docs/plans/conversation-reliability-repair.md).
The [website-task and stream recovery repair](docs/plans/assistant-website-recovery.md)
tracks working-deliverable planning, structured tool failures and claim-fenced
stream persistence during transient database contention.
Website-building tasks use an isolated owned project and return a checked offline
build with a ZIP download and interactive preview.
The [resource-wait reliability repair](docs/plans/runtime-sqlite-contention.md)
tracks per-Run admission backoff and durable recovery after transient SQLite contention.
The [web continuation repair](docs/plans/conversation-source-binding.md) binds
exact observed source URLs to their existing aliases before typed validation;
a completed Run alone is not treated as answer-quality evidence.

> **Early access:** AI Station brings desktop installers and guided model setup for
> Ubuntu 24.04 x86-64 and Windows 10 (21H2/22H2) or 11 x64. macOS is not supported yet.
> Windows 10 installation, login and worker execution were tested in a CPU-only VM.
> First local-model replies were tested separately on Windows 11; physical Windows
> NVIDIA tests and human evaluation of the new voice/film samples follow release.
> [Exact qualification and known issues](docs/releases/0.5.0.md).

**New in 0.4: a steadier voice.** Speech and avatars now balance loud and quiet
passages locally, without another AI model. Keep **Even voice volume** enabled
for new results, or turn it off for the original dynamics. For existing WAVs and
MP4s, open their Library details and choose **Even out voice volume**. You get a
separate copy; avatar video packets and timestamps stay unchanged.
[How it works and actual qualification](docs/plans/speech-volume-leveling.md).

**Windows 10 joins the station.** The desktop installer admits
Windows 10 21H2/22H2 x64 with KB5020030 or newer. It guides Windows support setup,
verifies Microsoft's WSL download and keeps your existing Linux distributions.
[Windows compatibility and prerequisites](docs/plans/windows-10-compatibility.md).

**Reliable conversations and working website results.**
Ask for a new website from a public source: the assistant reads it, creates an
isolated project and returns checked files with a ZIP and interactive preview.
Streaming preserves received text during transient database contention, and
follow-up tool decisions retain the original goal and source facts. This patch
also improves resource waits, model browsing and completed-avatar recognition.

**Model downloads, easier to find.** Open **Models → Add model**,
use hardware recommendations, search by name or paste a Hugging Face link.
**Quick setup** now shows only the category you choose, with clear navigation
on desktop and phone. Browse popular or
recently updated sources for conversation, images, video, voice, music, avatars
and memory — then review and install a compatible choice.

**Check the fit before downloading.** AI Station considers each GPU separately,
conversation context, RAM, disk and the complete model's companion files. It
explains unknown requirements and unsupported families instead of guessing.
Models sharing weights keep independent configurations; reusable owned files
reduce repeated downloads and are verified again during installation.

Your models become available in their workspaces and compatible assistant/agent
settings. Publisher update review is explicit: a new revision never replaces your
choice silently. [Supported families and actual tests](docs/models.md) ·
[Discovery design and installation lifecycle](docs/plans/open-model-discovery.md).

Release 0.5 retains reliable setup on Linux and Windows, your first local
result, and updates that keep your accounts, models and saved work.
[0.5.0 release notes and qualification status](docs/releases/0.5.0.md).

**In development: Creative Studio.** Organize reels, presentations and films by
brand, course or series, with a shared visual identity and editorial brief.
The first increment adds private projects, editable identities and grouping of
existing creative workspaces. Materials now have versioned briefs, scripts and
shot plans with a local director and an editable storyboard on develop. Generate
individual images or full video shots there, compare takes and open their Library
results without losing earlier work. Soundtrack production now chains local
narration, a score sized to the actual spoken passages, and a balanced mix; listen
to takes and apply measured timing without losing existing visuals. An isolated
Hyperframes renderer and the API/worker export bridge are qualified with actual
image/video fixtures. Export the selected takes and complete soundtrack from the
workspace, review earlier MP4s and download the result. The export panel can
activate a compatible engine already installed on the station, with private
setup history and Stop. When the engine is missing, guided preparation downloads
the fixed runtime components and builds it in bounded CPU containers, keeping
your other apps and AI models unchanged.
The export panel on develop can also add a completed avatar/presenter clip from
Library, with space beside or below the story. It keeps the film soundtrack and
requires enough footage for the complete edit. The production panel on develop
also offers **Create a speaking presenter**: choose a portrait and an installed
avatar model to generate the presenter from the film's actual narration. It
preserves the soundtrack and fits the story beside or above the presenter.
The conversation can select the supplied portrait for this same workflow.
An actual 17.2-second film now includes a newly generated Sonic presenter and
the exact original soundtrack. Complete decoding, timing and source/audio
identity checks passed; longer-film and audiovisual quality review continue.
A complete-material coordinator now queues sound, measured timing, missing shots
and export, with whole-production Stop and continuation that reuses complete
media and spoken cues. Broader generated film/voice quality remains in
qualification. This is not a feature
of the published 0.5.0 installers. [Delivery plan](docs/plans/creative-studio.md).
The conversation bridge adds semantic project/format/audio selection and queues
that same full production from a prompt, with a Studio link and final film in
chat. Account isolation, all four audio policies, Stop and queue recovery are
checked with fake media; actual conversational film quality remains in
qualification. New soundtrack finishing on develop measures and balances
publishing volume, protects peaks and retains exact narration timing; earlier
soundtracks keep their original audio. Complete generated-film quality remains
under review. Storyboards on develop can explicitly share one image or clip
across scenes while keeping separate captions, motion and timing. The director
fits new plans to the requested duration; manual edits remain explicit and
measured speech may extend the film rather than cutting words.
Real local-model checks now cover two distinct brands: an eight-second
widescreen silent presentation and a portrait music reel, each sharing one
generated image across scenes. Both final MP4s passed full decoding and the
requested duration/source checks; complete publication-quality review continues.
The bounded Wan engine also supports native portrait footage, preserving vertical
composition. A real four-second 704×1280 film passed two-window generation,
continuation and complete decoding. Each inference process used an enforced
11 GiB RAM limit with swap disabled. Source-video workflows on develop now
accept up to five minutes through the same segmented queue, Stop and resume;
long-duration queue/result handling is qualified separately from the short
real-GPU footage checks.

**One-click desktop updates.** Your app version stays
visible in the sidebar. In **Settings → Updates**, administrators can check the
new release and choose **Update and restart**. AI Station downloads and verifies
the official package, keeps your saved work, and reopens automatically. Linux and
Windows native update/recovery checks passed. Version 0.4 and older need the new
desktop client installed once before subsequent in-app updates become available;
development checkouts keep their normal development workflow.
[Update design and exact qualification](docs/plans/desktop-auto-update.md).

## Help make it simple

**We especially need testers and feedback.** Try AI Station on your hardware and
tell us what worked, what broke or what felt confusing. Setup friction and small
usability problems matter just as much as bugs. You don't need to write code to help.
Tell us what you tried, what you expected and what happened; include your operating
system and hardware if you know them. Please leave passwords and private files out
of public reports.
[Report a bug](https://github.com/jahu/ai-station/issues/new) ·
[Suggest an improvement](https://github.com/jahu/ai-station/issues/new?title=Suggestion%3A%20) ·
[Contribution guide](CONTRIBUTING.md).

## ✨ Made in AI Station. On a real home workstation.

A fictional presenter, a new outfit, a coastal photograph, a short film with its
own soundscape, and generated voices. These are real local outputs, created in a
separate **demo** account — with their prompts and execution history preserved.

<p align="center">
  <a href="website/assets/showcase/maya-original.webp"><img src="website/assets/showcase/maya-original.webp" width="270" alt="Before: fictional presenter generated locally with Qwen, wearing a navy blazer" /></a>
  <a href="website/assets/showcase/maya-edited.webp"><img src="website/assets/showcase/maya-edited.webp" width="270" alt="After: the same presenter edited locally with LUSTIFY, wearing an emerald blazer and gold brooch" /></a>
</p>

**Qwen creates the portrait. LUSTIFY changes the outfit.**
[Inspect the real portrait and prompt](website/assets/showcase/portrait-workspace.webp) ·
[Inspect the edit](website/assets/showcase/edit-workspace.webp).

[![Locally generated cinematic coastal scene with a classic burgundy car](website/assets/showcase/coastal-original.webp)](https://ai-station.dev/#showcase)

**An image becomes a film, then gets its own sound.** The scene above was generated
with Qwen, animated with Wan 2.2 and given a harbor soundscape with MMAudio.
[Watch and listen to the real examples](https://ai-station.dev/#showcase), including
original English speech and clearly labeled synthetic reference-voice impressions
based on Morgan Freeman, Donald Trump, Elon Musk, Oprah Winfrey and Michelle Obama.
The impressions speak English; they are not authentic recordings, endorsements or
official built-in celebrity voice presets.

**Text becomes a film, with its own sound.** No reference image: a written
coastal-portrait description becomes a short Wan 2.2 scene, then MMAudio generates
the ocean ambience. The fictional person, motion and sound are created locally.
Three generated segments form the continuous shot.
Native 1280 × 704, 8 seconds, 24 fps; no upscale or face retouching.

<p align="center"><a href="https://ai-station.dev/#text-to-video"><img src="website/assets/showcase/text-video-poster.webp" width="720" alt="Actual frame from a locally text-generated film of a fictional adult woman by the ocean, with generated coastal sound" /></a></p>

[Watch the text-to-video example with sound and inspect its prompts](https://ai-station.dev/#text-to-video).

**Two moods. Two original soundtracks.** Hear “First Light”, a cinematic piano-and-strings instrumental, and “Little Signals”, bright synthpop with a synthetic English vocal. Both are complete 45-second local ACE-Step 1.5 Turbo generations, with prompts and generation settings beside the players. [Listen to the music examples](https://ai-station.dev/#music-title).

**One prompt, connected tools.** Supply a portrait and a recording, then ask for
a studio presenter. The local assistant created the studio image, observed its
actual result and passed it with the supplied recording to Sonic. Both outputs
remain in the same conversation. The film below is the real 12.76-second result,
shown at native 512 × 640 resolution without face retouching or upscaling.

<p align="center"><a href="https://ai-station.dev/#workflow-title"><img src="website/assets/showcase/avatar-poster.webp" width="320" alt="Frame from the real locally generated speaking-avatar film of the fictional presenter in a television studio" /></a></p>

[Watch the real two-tool example, with captions](https://ai-station.dev/#workflow-title).
The voice was generated separately and supplied as an input; the demonstration
does not pretend TTS was a third tool call in that request.

**Made on an i7-6900K, 32 GB RAM and two RTX 3060 12 GB GPUs.** Faster hardware can
reduce generation time; additional VRAM can enable larger models and higher
settings. Image quality depends on the model and settings as well as the task.
Public examples stay safe for work; compatible uncensored models also support
adult/NSFW creation without an extra AI Station content filter.

Want to try your own idea? [Get started](#-get-started),
[share your results or report a problem](https://github.com/jahu/ai-station/issues/new),
or [help develop the platform](CONTRIBUTING.md).

## 🎛 One station. Many ways to create.

| You want to… | AI Station gives you… |
| --- | --- |
| **Talk and think** | Streaming conversations, local model selection, optional reasoning controls, attachments, web search and page reading. |
| **Make and transform images** | Generate, Edit, Recompose and Upscale; ordered references, prompts, parameters and reusable results. |
| **Create video and avatars** | Local video generation, multi-shot films, resumable segments and portraits animated against a recording or generated speech. |
| **Work with sound** | Speech from text and a reference voice, transcription and local music generation. |
| **Put agents to work** | [Recurring image variations](docs/plans/agent-image-scenes.md), natural-language drafts, in-chat image model selection and approval, reviewed tools and permissions, schedules, history, in-app notices and confirmed single or bulk deletion. |
| **Do something with your files** | Local spreadsheet/document analysis, Python tools, generated files and isolated website/project workflows with follow-ups. |
| **Keep your creative work** | Your private media-first Library, searchable reusable inputs, film previews, source lineage, downloads, metadata, Trash and confirmed permanent deletion. |
| **Operate your workstation** | Owned llama.cpp models, GPU allocation, runtime health, memory, diagnostics and inspectable Runs. |

Optional [Fish S2 Pro speech](docs/plans/expressive-speech.md)
adds a model choice, delivery directions and pacing in Audio and reviewed speech
agents. Choose **Generate a voice** for expressive delivery, or **Use a recording**
to keep a particular speaker; a neutral recording can soften emotional delivery.
Slower/Faster adjusts speaking speed while preserving pitch; Natural keeps the
model's original pace.
It requires a configured two-GPU runtime and retains Fish Audio's separate
model license. Chatterbox remains the default. Audio offers Polish or English
when the selected adapter supports it; older Polish adapters remain compatible.
Historical v0.0.2 packages are unchanged.

<table>
<tr>
<td width="50%"><img src="website/assets/conversation.png" alt="Real AI Station Chat with a completed local Qwen film-planning reply" /></td>
<td width="50%"><img src="website/assets/video.png" alt="Actual Video workspace with the source image, motion prompt and completed eight-second coastal film" /></td>
</tr>
<tr><td align="center"><strong>One conversation to begin.</strong></td><td align="center"><strong>A workspace when you want control.</strong></td></tr>
</table>

<details>
<summary>Explore the Library and agent workspace</summary>

![Real demo Library with generated photos, an outfit edit and completed films](website/assets/library.png)
![Actual Agents workspace with a saved, paused daily market-research draft](website/assets/agents.png)

</details>

*Chat and Library show real completed generations in a separate demo account, captured at 2× resolution. No operator Library or fabricated messages. Video shows the real completed eight-second coastal job. Agents shows a saved review draft, without claiming it has executed. The animated tour retains its historical demonstration provenance. [Media provenance](website/asset-provenance.json).*

**One prompt. Your own autonomous agent.** Describe the job and how often it should run.
AI Station prepares the instructions, tools and schedule for your review; enable
it when you're ready. Create regular images or short videos, research topics,
analyze files and automate recurring jobs with local code when needed.
Direct social publishing integrations are planned.

[Explore agent ideas](https://ai-station.dev/#agents-showcase), including a
[recorded market-research example](https://ai-station.dev/#market-agent-title)
with its actual [brief](website/assets/showcase/market-report.txt),
[chart](website/assets/showcase/market-chart.png) and
[CSV](website/assets/showcase/market-prices.csv). That example uses closing data
through 6 November 2026; its daily trigger is paused after the demo.

Automatic multi-tool conversations are being qualified for the next development build: describe a
complete outcome, and the assistant can research, create an image, transform the
result and prepare a recurring agent draft in the same conversation. Each step
retains its real status, sources, artifacts and Stop control; agents still require
review before activation. The current repair adds a LlamaIndex ReAct loop, persistent
conversation references and exact result/cadence bindings for recurring image
agents. [Implementation and verification status](docs/plans/conversation-reliability-repair.md).

## 🔓 Local by choice. Yours to control.

**No platform censorship. No cloud inference account required for local workflows.** Run
compatible models on your workstation, keep your files and history there, and
choose the models you want — including compatible uncensored weights. You choose the model, its capabilities
and its behavior.

Compatible uncensored models can also be used for adult/NSFW creation. The chosen
model and runtime determine supported content and behavior; AI Station does not
remove a model's built-in restrictions or make every model format compatible.

You are responsible for the inputs you use, the content you create and how you
share it, including consent, privacy, intellectual-property rights, applicable
law and each model's license. The software is provided under the warranty and
liability terms of the [license](LICENSE); those terms do not override applicable
law or grant permission to misuse someone else's content or likeness.

Local generation uses your hardware, with no AI Station per-token charge. Your
conversations, artifacts and application state live on your workstation. External
inference is opt-in; web search, downloads and private remote access use networks.
Choose the tools you want for each task.

Model choice is broad; machine access stays explicit. Agents use reviewed tools,
owned workspaces and scoped permissions. You can inspect what ran, where it ran,
what changed and which files it produced.

Media jobs retain supervision across temporary database contention and can resume
inspection of an already-owned process after a worker disappears, without starting
generation again. [Recovery contract](docs/plans/media-lease-recovery.md).

## 🧭 How does it fit alongside other projects?

These projects cover overlapping ground. Here is where each places its emphasis
and why you might choose AI Station alongside them.

| Project | Its emphasis | AI Station's emphasis |
| --- | --- | --- |
| [Open WebUI](https://docs.openwebui.com/features/) | A broad AI interface spanning conversations, knowledge, tools, voice, images and automations. | Bring that conversation into a host-aware workstation with a shared lifecycle for models, media, local agent jobs and artifacts. |
| [LM Studio](https://lmstudio.ai/docs/app/offline) | Download and run local LLMs, chat with documents and serve local inference. | Coordinate LLMs alongside image, video, audio and persistent agent workflows in one place. |
| [AnythingLLM](https://docs.anythingllm.com/chatting-with-documents/introduction) | Document-centered workspaces, retrieval and [tool-using agents](https://docs.anythingllm.com/features/ai-agents). | Keep knowledge and agents alongside creative media, GPU resources and inspectable execution. |
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | A visual graph and execution engine for generative-media workflows. | Offer an everyday conversation and focused workspaces while integrating configured media runtimes underneath. |
| [Pinokio](https://desktop.pinokio.co/) | Discover, install, launch and automate local apps. | Build a connected experience across tasks, conversations, models and results, rather than asking the user to manage each app separately. |
| [Maestro / RunMaestro](https://github.com/RunMaestro/Maestro) | Coordinate coding agents and multiple projects from a desktop command center. | Put coding-capable agents inside a broader personal AI workstation for media, research, files and automation. |

These tools can coexist. AI Station can use compatible existing services;
you do not have to replace a working local setup to adopt the control plane.

## ⚡ Real hardware. Real results.

Measured on an **Intel Core i7-6900K, 32 GB RAM and two NVIDIA RTX 3060 12 GB cards**.
This is the development workstation, not a minimum requirement or a hard-coded
hardware profile. Two GPUs provide separate 12 GB devices, not a universal 24 GB pool.

| Workload | Recorded settings | Observed result |
| --- | --- | --- |
| **Local LLM generation** | RVN 27B Q4_K_M; llama.cpp; both GPUs; 46,080-token context allocation; Q8 KV cache; 467 prompt / 345 generated tokens | **16.9 generated tokens/s**; prompt processing **380.2 tokens/s**, measured separately. |
| **Generate an image** | LUSTIFY v10 Turbo Q4_0; 768×1024; 8 steps; CFG 1; two-GPU profile | **1 min 40 s** |
| **Edit an image** | Same model/size/steps; one reference, aligned layout | **2 min 27 s** |
| **Recompose an image** | Same model/size/steps; one reference, beside layout | **2 min 29 s** |
| **Recompose with two references** | Same model/size/steps; ordered scene and person references | **3 min 10 s** |
| **Generate two video shots in parallel** | Wan2.2 5B; 2 × 2-second shots; 1280×704; 20 steps; separate GPUs | **7 min 58 s** for the full four-second film and composition. |
| **Generate a continuous one-minute film** | Wan2.2 5B; 1280×704; 24 fps; 20 steps; 18 sequential windows; bounded host RAM | **3 h 16 min** for the complete 1,440-frame workflow. |
| **Create a one-minute speaking avatar** | EchoMimic V3; 384 px; 8 steps; 24 windows; one GPU; 60-second recording | **48 min 18 s**, including fresh source-speech preparation and composition. |
| **Create a whole-recording avatar with more detail** | Sonic; native 512×768; 25 steps; both GPUs; complete 40.08-second recording | **2 h 27 min 18 s** end to end; 1,002 frames at 25 fps. Owner confirms substantially improved quality; not native HD. |

These are recorded observations, not a cross-project benchmark or a speed promise.
The LLM row is one captured completion; allocated context is not prompt length.
Media times include their recorded Run/workflow boundaries, not diffusion-only
kernel speed. Historical long-video and Echo avatar results retain their observed
color/facial-detail limitations. The newer Sonic result received positive owner
feedback; duration success alone is not a promise of perfect visual quality.
[Method, exact scope and evidence](docs/benchmarks.md).

## 🚀 Get started

**[Try the current release →](https://github.com/jahu/ai-station/releases/latest)**

Download the package for your computer from the release assets:

- **Windows 10 (21H2/22H2) or 11 x64:** `AI-Station-0.5.0-windows-x64-Setup.exe`.
- **Ubuntu 24.04 x86-64:** `AI-Station-0.5.0-linux-amd64.deb`.

Open AI Station, follow the setup, create your administrator account and choose
a recommended model. Downloads show their size and license before you agree.
Python and the app are bundled; the installer guides required OS permissions.
Windows uses its own WSL2 environment and may require an OS restart. Windows 10
needs KB5020030 or a newer cumulative update (build 19044/19045, revision 2311+).
Setup points you to Windows Update when needed. **Set up Windows support** prepares
WSL with your Windows permission, downloading about 370 MB from Microsoft when
WSL is missing; Docker Desktop and a separate Ubuntu installation are unnecessary.
Model downloads and larger media need additional disk space and suitable hardware.

**Windows installer notice:** the installer is **not digitally signed**. Windows may show
an unknown-publisher/SmartScreen warning; Smart App Control or managed-device
policies may block it. Use only this repository's official assets and compare
`SHA256SUMS`. Do not disable system protections. Signing is planned for a later
release. A checksum checks file identity; it does not replace a code signature.

[Installation, updates and known issues](docs/releases/0.5.0.md).
The manual Linux path remains available below for advanced users.

<details>
<summary><strong>Advanced: manual Linux setup from source</strong></summary>

**Current release prerequisites:** Linux, Git, Python 3.12 with venv support,
Docker Engine and Docker Compose. GPU media additionally requires a compatible
configured runtime and model. The currently exercised media paths use NVIDIA/CUDA;
other GPU vendors remain a compatibility goal, not a blanket hardware-support claim.

```bash
git clone --branch master https://github.com/jahu/ai-station.git
cd ai-station
cp .env.example .env
./scripts/bootstrap.sh
# Configure your existing model/runtime paths in .env — see the setup guide.
./scripts/start.sh
```

Open **http://127.0.0.1:8765**. Your models and integrations report their real
availability; starting the app does not silently download a model collection.

**[Follow the setup guide →](docs/getting-started.md)** for configuration, existing
llama.cpp/Ollama services, optional media runtimes and development commands.
[Download the latest release](https://github.com/jahu/ai-station/releases/latest).
[What's new in 0.0.2](docs/releases/0.0.2.md). `master` is the release branch; contributors work through
feature branches and PRs into `develop`.

</details>

<details>
<summary><strong>Explore 0.1 features and guided model setup</strong></summary>

**0.2** adds [open model discovery](docs/plans/open-model-discovery.md) to the
existing [0.1 foundation](docs/plans/next-release-0.1.md):
private accounts, persistent creative workspaces, prompt/search improvements,
expressive audio, timeline editing and guided setup. Qualified hardware and
post-release QA are listed in the [release notes](docs/releases/0.5.0.md).

Private accounts provide per-user
conversations, Library, memory and agents, with shared models/hardware, optional
two-factor authentication and administrator management. They are an explicit
access-profile cutover; see [accounts and migration](docs/accounts.md).

**Models → Set up a local model** offers reviewed local
conversation-model downloads. See actual RAM/VRAM and free application storage,
accept the model license, stop/resume preparation and open Chat after verification.
This Linux route can prepare a reviewed llama.cpp runtime image, then download
your selected model. Existing configured images stay available. Cross-platform
launchers and full media setup remain in progress.
[Guided setup and measured qualification](docs/plans/guided-model-installation.md).

On Linux x86-64 without an NVIDIA GPU, model setup offers a small **CPU
conversation model**. Review its source and RAM estimate, prepare the engine,
then open Chat. This explicit profile uses system RAM and a 4096-token context;
it is slower than GPU inference. Existing GPU/external models stay selected
until you choose another model. [CPU setup](docs/plans/guided-cpu-conversation.md).

On supported Linux NVIDIA workstations, the same page offers **Set up local
speech**: review hardware, storage and component licenses, prepare Chatterbox,
then open Audio with your reference recording. Setup history and Stop/Resume are
saved; an existing configured speech runtime keeps priority. This setup
flow prepares its own Python and offline dependencies, rather than asking you to
wire up a separate environment.
[Speech setup and qualification](docs/plans/managed-speech-setup.md).


On supported Linux NVIDIA workstations with two 12-GiB GPUs, **Set up images**
reviews the Qwen/RealESRGAN sources and licenses, prepares the engine and all
companions, and opens the saved Images workspace for Generate, Edit, Recompose
and Upscale. Stop/Resume and download verification use normal private Runs;
existing configured image integrations keep priority.
[Image setup and measured qualification](docs/plans/managed-image-setup.md).

**Set up memory** prepares a small multilingual CPU model for searching saved
knowledge by meaning. The app shows sources, license and storage before setup;
your GPUs stay free and memory content remains private. Existing embedding
endpoints remain selected unless you explicitly replace them.
[Memory setup](docs/plans/memory-embeddings-readiness.md).

Development builds can also inspect and install compatible E5 F32 encoder bundles
from a Hugging Face link. Hardware and complete storage estimates come first;
choosing **Use for memory** explicitly switches the CPU encoder and rebuilds your
private index. [Supported imports](docs/models.md#discovered-memory-encoder-bundles-candidate-under-qualification).

**Set up music** prepares ACE-Step 1.5 Turbo on supported Linux NVIDIA
workstations with at least 12 GiB VRAM and 24 GiB system RAM. Review sources and
component licenses, install with saved progress and Stop/Resume, then create an
instrumental or use your own lyrics in Music. This profile uses CPU offload;
existing configured ACE-Step environments keep priority.
[Music setup and measured qualification](docs/plans/managed-music-setup.md).

Development builds also support explicit installation and selection of
compatible ACE-Step music checkpoints from publisher links, with complete
hardware/component review and preserved engine bindings.
[Music model imports](docs/models.md#discovered-music-bundles-under-qualification).

**Set up video** prepares Wan 2.2 5B on supported Linux NVIDIA workstations
with at least 12 GiB VRAM, 24 GiB system RAM and a compatible driver. Review
sources, component licenses and storage, then install with saved progress and
Stop/Resume. Create a scene, animate an image or continue a longer film in Video;
the prepared environment also handles final composition and CPU timeline export.
Existing configured video integrations keep priority.
[Video setup and measured qualification](docs/plans/managed-video-setup.md).



**Set up avatars** prepares Sonic on supported Linux NVIDIA workstations with
at least 12 GiB VRAM, 24 GiB system RAM and a compatible driver. Review the
component licenses, install with saved progress and Stop/Resume, then animate a
portrait with your complete recording. The prepared engine includes its own
Python and finishing codec. Existing Sonic and EchoMimic configurations are
preserved; installing Sonic does not install EchoMimic. Output is up to 768 px,
rather than native HD. [Avatar setup and qualification](docs/plans/managed-avatar-setup.md).

**Set up sound effects** prepares the existing MMAudio film-sound engine,
companions and CPU finishing tools on supported Linux BF16-capable NVIDIA
workstations. Review hardware, space and component terms, install with saved
Stop/Resume, then add scene sounds to a film in Audio. This is a **research
profile**: the Apple CLIP component has a research-only license and MMAudio
checkpoints have separate noncommercial terms. Existing configured engines stay
selected. [Sound setup and measured qualification](docs/plans/managed-effects-setup.md).

**Set up expressive voice** prepares Fish S2 Pro and local reference transcription
on supported Linux BF16-capable NVIDIA workstations with two GPUs (10 + 5 GiB
VRAM) and 24 GiB system RAM. Add a phone recording, enter your script and choose
delivery and pace in Audio. Model weights stay on GPUs; setup progress and
Stop/Resume use private ordinary Runs. Existing Fish/Whisper settings retain
priority. Review the component licenses before installation.
[Expressive voice setup and qualification](docs/plans/managed-fish-setup.md).

Desktop packages bundle Python and the application image, open
account/model setup in your browser and keep data outside the installed package.
Clean installation, a real first CPU conversation and preserving update/reinstall
have been verified on [Linux x86-64](docs/plans/linux-consumer-qualification.md)
and [Windows 11 / WSL2](docs/plans/windows-consumer-installation.md).
The [Windows 10 extension](docs/plans/windows-10-compatibility.md) records its
separate installation, prerequisite and runtime qualification.
The Linux package explains any required Docker permission through a native dialog
and keeps the app running as your ordinary user. Physical Windows NVIDIA and
combined fresh Linux GPU qualification remain unverified; CPU first use and
existing Linux GPU profiles have separate actual evidence.
[Desktop packaging and status](docs/plans/desktop-installation.md).

**Known issue — macOS:** the native installer is **not supported in release 0.2**.
Full installed startup remains unreliable; the latest attempt timed out waiting
for Docker Desktop's local engine before account/model setup. Passing native
component tests does not establish a working Mac installation. Mac work is
deferred so it does not delay Linux and Windows. Existing experimental source
and evidence are retained. [Mac status](docs/plans/macos-consumer-installation.md).

Development builds also retain creative sessions across Images, Video, Music,
Speech and Avatars. Measured generation stages and scoped time estimates use
saved observations rather than a simulated countdown. See
[creative workspaces](docs/creative-workspaces.md) and
[generation progress](docs/plans/generation-progress.md).

Development builds offer **Improve my prompt locally** in Images, Video, Music
and Echo avatar workspaces. Choose your local preparation model in Settings →
Generation, optionally review its wording, and keep the original beside the
effective prompt. Lyrics and spoken scripts are preserved. Fixed Sonic and
upscale operations have no descriptive prompt to enhance.
[Prompt preparation contracts](docs/plans/local-prompt-enhancement.md).

For edits, **Auto · match this edit** offers a visible
model recommendation. Pose changes and object removal can use Qwen while explicit
LUSTIFY choices remain available. [Image workflows](docs/image-workflows.md).

Speech offers optional **Shape the delivery** controls for a
compatible configured Chatterbox CLI. Expression, guidance and variation stay with
each version; the spoken script and standard defaults remain intact.
[Speech controls and qualification](docs/plans/expressive-speech.md).

**Sound effects** in Audio lets you choose a completed
film, describe its sounds and keep both a reusable WAV track and a synchronized
video preview. **Add sound** on a film opens the saved workspace with that source.
The optional offline MMAudio runtime uses one GPU and retains its separate
noncommercial model license. [Configuration and qualification](docs/plans/synchronized-sound.md).

### Saved film editing

Video → **Edit a film** opens a saved editing workspace. Add inspected films and
WAV speech, music or effects from Library; trim, move and reorder clips, adjust
volume, mute and fades, and inspect measured waveforms. Save immutable edits and
return to them later. **Preview this edit** renders the actual saved mix;
**Export film** downloads that same verified result. Changing the draft marks an
older preview and requires a new render before export. Source files and earlier
results remain in Library. CPU rendering uses an owned four-GiB/zero-swap scope
and does not unload GPU models. See [timeline contracts](docs/plans/media-timeline.md)
for supported timing, private ownership and qualification gates.

### Film sound agents

In an agent's **Create media** settings choose **Sound effects**, select a film
from your Library and describe what should be heard. Optional scene directions
keep exact start/end times. Use the saved description each run, or let the
selected local model write a new overall description from the reviewed goal.
The film, scene directions and generation settings stay fixed. Review and enable
the definition, then Run now or use its saved schedule. Each execution retains a
separate effects WAV and a synchronized video preview; the original film remains
unchanged. Missing sources or an unavailable local engine block activation.


### Film sound in the conversation

Ask **“Add sound to this film: rain on the leaves”** after a completed film,
or choose **Attach files & choose tools → Add film sound** and select it from
Library. Original audio is kept by default; replacing it is an explicit option.
For a new film, choose **Generate video → Add sound to this film** and describe
what should be heard. The conversation retains a synchronized movie, separate
WAV and **Edit sound mix** link to its saved timeline. Film, effects and mixing
share one inspectable, stoppable task. This uses the optional configured MMAudio
runtime above; narration and music remain separate capabilities.

</details>

## 🌱 Where we're going

The ambition is simple: **a person with a home GPU should be able to install
AI Station and start creating without learning model servers, Python environments
or GPU flags.** A familiar chat experience, plus local tools for the things you
would otherwise spread across separate AI apps.

- **Guided first launch:** detect hardware, explain what fits and offer sensible defaults.
- **Model setup inside the app:** explicit downloads, verified files, progress, cancellation and storage estimates.
- **Easier media setup:** prepare compatible runtimes and presets instead of asking people to wire them together.
- **Hardware-aware choices:** propose a model, quantization and context that fit the available devices.
- **A friendlier daily experience:** clearer language, strong mobile UX and optional push notifications.
- **Simpler installation and updates:** an illustrated setup guide and in-app updates that keep your work. [Implementation and qualification plan](docs/plans/desktop-auto-update.md).
- **More capabilities over time:** additional models, runtimes and devices through the existing execution boundaries.

The goal is the familiarity of a ChatGPT-style conversation and a creative suite,
powered by local models such as llama.cpp-compatible LLMs, Wan, Sonic, EchoMimic,
Chatterbox and ACE-Step. [The consumer setup plan](docs/plans/consumer-first-setup.md)
keeps that direction concrete.

## 🏗 A workstation, with a control plane

The interface can be simple while the execution stays visible.
Every workload follows **Task → Run → Events → Artifacts**.

```mermaid
flowchart TB
    User["You · conversation or workspace"] --> UI
    subgraph Control["Docker control plane"]
        UI["React interface"] --> API["FastAPI · task intent"]
        API --> Engine["Run engine · workers · permissions"]
        Scheduler["Persistent scheduler"] --> Engine
        Engine --> State["SQLite · events · memory · artifact metadata"]
    end
    Engine -->|"Typed HTTP over a private Unix socket"| Runner
    subgraph Host["Native user-level Host Runner"]
        Runner["Validate paths · own processes · enforce limits"]
        Runner --> LLM["llama.cpp · local models"]
        Runner --> Media["Image · video · voice · music runtimes"]
        Runner --> Tools["Git worktrees · bounded code and file tools"]
    end
    LLM --> Hardware["Discovered GPUs and CPU"]
    Media --> Hardware
    Tools --> Results["Files and results"]
    Media --> Results
    Results --> Library["Library · conversation · Run history"]
    State --> Library
    style Control fill:#101b14,stroke:#3e5940,color:#d9e8d0
    style Host fill:#101b14,stroke:#3e5940,color:#d9e8d0
    classDef normal fill:#18221a,color:#e1edda,stroke:#42543a
    class User,API,Engine,Scheduler,State,LLM,Media,Tools,Hardware,Results normal
    classDef accent fill:#b9f58a,color:#10150f,stroke:#b9f58a
    class UI,Runner,Library accent
```

The Docker control plane gets no privileged container, Docker socket or unrestricted
host mount. The native Runner exposes typed operations, not an arbitrary shell.
Existing external services keep their ownership. Cloud providers are optional
adapters, not a dependency of the local execution path.

<details>
<summary><strong>For builders: architecture, development and verification</strong></summary>

The foundation is a modular monolith: FastAPI, SQLAlchemy/Alembic and SQLite WAL,
React/TypeScript/Vite, a durable worker/scheduler and a private native bridge.

```bash
./scripts/dev.sh
./scripts/check-all.sh
```

Normal tests use temporary databases and fake executors. Expensive real integrations
are opt-in. The 0.1 Python regression passed **8,020 tests**, with 19 explicit skips;
late package/helper changes additionally passed 77 and 159 affected cases.
Frontend/build and actual packaged platform evidence is recorded separately;
unchanged code is not described as freshly retested. The offline QA tools pass
29 tests. These results do not automatically qualify every model, media profile
or machine.
[Release verification](docs/releases/0.5.0.md#qualification) ·
[Historical verification](docs/verification.md) · [Operator QA](docs/qa/README.md).

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before contributing. The [setup/development guide](docs/getting-started.md)
also explains how to add executors, capabilities, providers, tools and connectors.

</details>

| Explore | Guides |
| --- | --- |
| Project landing page | [Standalone website source and local preview](website/README.md) |
| Understand the platform | [Architecture](docs/architecture.md) · [Security](docs/security-model.md) · [Execution](docs/execution-model.md) |
| Run local models | [Models](docs/models.md) · [llama.cpp](docs/managed-llama.md) · [Chat](docs/local-chat.md) |
| Create media | [Images](docs/image-workflows.md) · [Video](docs/video.md) · [Avatars](docs/avatars.md) · [Audio](docs/audio.md) |
| Work with agents | [Agents](docs/agents.md) · [Projects](docs/projects.md) · [Memory](docs/memory.md) |
| Operate your station | [Library](docs/library.md) · [Private access](docs/private-network-access.md) · [Backups](docs/operations.md) |

---

## 📜 License

**Free for noncommercial use. Commercial use requires a separate written license.**
AI Station is source-available under [PolyForm Noncommercial 1.0.0](LICENSE),
including its expressly permitted organizational uses. You can inspect, modify
and share it for permitted purposes. [Commercial licensing and details →](COMMERCIAL.md)

Contributions are welcome; contributors retain their copyright and provide the
separate permission needed for commercial licensing. Models and dependencies
keep their own licenses. [Contribution guide](CONTRIBUTING.md) · [Required notice](NOTICE)

**Local AI, made simple.** ✳

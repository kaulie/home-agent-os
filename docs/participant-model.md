> 固化自 `/Users/gaolei/devspace/home-agent-docs/home_agent_participate_model.txt`（2026-08-18）。Prompt、Runtime Protocol、Registry 以本模型为准。
>
> **命名不要混：** 文中 Role **Observer** = 消费系统事件的 Participant（CLI / Dashboard）。Cursor 会话 **system coordinator agent / `@coordinator`** = 团队协调员，不是这个 Role。旧称 `@observer` 仅历史信箱有效。
>
> Endpoint 功能契约补充：[`endpoint-contract.md`](endpoint-contract.md)。Cast 呈现协议：[`chromecast-cast-protocol.md`](chromecast-cast-protocol.md)。
可以。今天这个其实已经不只是对 Endpoint 的补充，而是把 **Home Agent 的 Participant Model** 基本定型了。我建议把它单独固化成架构文档，后面 Prompt、Runtime Protocol、Registry 都以这个模型为准。

# Home Agent Participant Model

## 1. Overview

Home Agent 不应以“设备类型”作为系统参与者的核心抽象，而应以：

> **Participant + Role + Contract**

作为统一的参与者模型。

一个物理设备可以同时承担多个不同角色。

例如，一个 iPhone 可以同时是：

* Intent Source：接收用户语音并产生 Intent
* Runtime Agent：执行 GoPro 相关 Capability
* Endpoint：接收并呈现最终结果
* Observer：观察 Home Agent 的运行状态

这些角色彼此独立，不应因为它们运行在同一个物理设备上而混淆。

因此：

```text
Participant
    ↓
Identity
    ↓
Roles
    ├── Intent Source
    ├── Runtime Agent
    ├── Endpoint
    └── Observer
```

Role 是逻辑身份，Device 只是 Participant 的一种物理承载形式。

---

# 2. Participant

## 2.1 Definition

Participant 是任何参与 Home Agent 系统的实体。

Participant 可以是：

* iPhone
* Mac
* Kindle
* GoPro
* ESP32
* Speaker
* Web Dashboard
* CLI
* Cursor Agent
* 其他未来设备或软件节点

Participant 必须首先向 Home Agent 声明自己的 Identity。

Conceptually:

```text
Participant
├── Identity
└── Roles
```

Participant 不要求必须具备任何特定 Role。

因此一个 Participant 可以：

```text
只作为 Endpoint
```

也可以：

```text
同时作为 Intent Source + Runtime + Endpoint
```

甚至：

```text
只作为 Observer
```

---

# 3. Identity

Identity 用于回答：

> **“你是谁？”**

Identity 与 Role 分离。

例如：

```text
Participant
    identity:
        participant_id = iphone_xxx
        device_type = iphone
```

Identity 主要用于：

* Participant 注册
* Participant 寻址
* 权限控制
* Event 关联
* Endpoint 关联
* Runtime 关联
* Intent Source 关联
* Observer 订阅

Home Agent 不应仅依赖 `device_type` 判断 Participant 能做什么。

真正决定 Participant 能参与什么的是它注册时声明的 Roles 和对应 Contracts。

---

# 4. Roles

Home Agent 当前定义四种核心 Role：

```text
Intent Source
Runtime Agent
Endpoint
Observer
```

四种 Role 是正交的。

它们不是互斥类型。

同一个 Participant 可以同时拥有多个 Role。

---

# 5. Intent Source

## 5.1 Definition

Intent Source 是能够向 Home Agent 提供用户意图或其他输入意图的参与者接口。

它回答：

> **“我能从哪里获得 Intent？”**

例如：

```text
iPhone microphone
voice assistant
smart watch
touch UI
CLI
web UI
```

Intent Source 产生：

```text
Intent
    ↓
Home Agent Brain
```

Intent Source 不负责规划 Capability，也不负责决定最终 Presentation。

---

## 5.2 Example

iPhone：

```text
Participant: iPhone

Role:
    Intent Source

Source:
    microphone
```

用户说：

> “拍一张照片我看看。”

iPhone microphone 产生 Intent：

```text
Intent
    "拍一张照片我看看"
```

然后交给 Brain。

---

# 6. Runtime Agent

## 6.1 Definition

Runtime Agent 是能够代表 Home Agent 执行 Capability 的参与者。

它回答：

> **“我能替 Home Agent 做什么？”**

Runtime Agent 注册自己能够执行的 Capability。

例如 GoPro：

```text
Participant: GoPro

Role:
    Runtime Agent

Capabilities:
    camera.take_photo
```

或者：

```text
Participant: iPhone

Role:
    Runtime Agent

Capabilities:
    gopro.take_photo
    gopro.download_photo
```

---

## 6.2 Runtime 与物理设备解耦

Capability 属于 Runtime Contract，而不是天然属于物理设备。

例如：

```text
iPhone
    └── Runtime Agent
          └── gopro.take_photo
```

以后也可以迁移成：

```text
Mac
    └── Runtime Agent
          └── gopro.take_photo
```

Brain 不需要改变 Intent 或上层规划逻辑。

Brain 只需要根据 Registry 找到当前可用的 Runtime。

---

# 7. Endpoint

## 7.1 Definition

Endpoint 是 Home Agent 向用户交付最终结果的出口。

它回答：

> **“我能通过什么方式接收并呈现 Home Agent 的结果？”**

Endpoint 不负责理解用户 Intent。

Endpoint 也不负责决定应该呈现什么。

这些属于 Brain 的职责。

Endpoint 负责：

> **遵循 Home Agent Presentation Protocol，将 Brain 下发的 Presentation 按照协议进行渲染、播放或呈现。**

---

# 8. Endpoint Contract

Endpoint 注册时需要声明自己支持的 Presentation 类型。

例如 Kindle：

```text
Participant:
    Kindle

Role:
    Endpoint

Endpoint:
    kindle_browser

Supported Presentation:
    html
    text
    image
```

这意味着 Brain 可以知道：

```text
Kindle Endpoint
    supports:
        html
        text
        image
```

因此 Brain 可以根据 Presentation Plan 进行 Endpoint Matching。

例如：

```text
Presentation:
    type = image
```

Brain 可以选择：

```text
kindle_browser
```

如果 Presentation 是：

```text
type = audio
```

而 Kindle 没有声明支持 audio，则该 Endpoint 不满足要求。

---

# 9. Endpoint 不等于 Device

一个 Participant 可以拥有多个 Endpoint。

例如：

```text
iPhone
├── Endpoint
│    ├── display
│    └── speaker
```

因此 Presentation 的目标不应简单地写成：

```text
endpoint = iphone
```

而应能够精确定位：

```text
endpoint = iphone.display
```

或者：

```text
endpoint = iphone.speaker
```

这样同一个 Participant 可以同时承担多个不同的用户输出通道。

---

# 10. Presentation

Presentation 是 Brain 在执行完成后，为用户构造最终结果的过程和描述。

它回答：

> **“用户最终应该得到什么？”**

Presentation 与 Capability 平级，而不是 Capability 的一个附属属性。

完整的数据流是：

```text
User Intent
    ↓
Brain
    ↓
Execution Plan
    ↓
Runtime
    ↓
Execution Results
    ↓
Presentation Resolution
    ↓
Presentation
    ↓
Endpoint
```

---

# 11. Execution Result ≠ User-facing Result

Runtime 产生的结果不一定就是最终交付给用户的结果。

例如：

```text
GoPro.take_photo
    ↓
photo_url
```

这是 Execution Result。

如果用户说：

> “拍一张照片我看看。”

Brain 可以规划：

```text
Presentation:
    type = image
    source = photo_url
```

然后直接把 photo URL 作为最终 Presentation Payload 交给 Endpoint。

---

# 12. Presentation 可以跨 Step 获取结果

Presentation 不要求结果必须来自最后一个 Step。

Brain 拥有整个 Execution Context，因此可以知道：

```text
Step 1 → Result A
Step 2 → Result B
Step 3 → Result C
...
Step N → Result N
```

最终用户可能只需要：

```text
A + D + F
```

Brain 可以选择这些结果作为 Presentation 的输入。

因此：

> **Presentation Source 可以来自执行图中的任意相关 Step。**

---

# 13. Presentation Resolution

Presentation 在交付给用户之前，可能需要一个最终的 Result Resolution 过程。

Result Resolution 可以包括：

* Result Selection
* Aggregation
* Computing
* Transformation
* Formatting
* Combination

概念上：

```text
Execution Results
        ↓
Result Resolution
        ↓
User-facing Result
        ↓
Presentation
        ↓
Endpoint
```

---

# 14. Example：房子里有几个人

用户：

> “现在房子里一共有几个人？”

Brain 规划：

```text
Step 1:
    living_room_camera
        ↓
    person_count = 1

Step 2:
    kitchen_camera
        ↓
    person_count = 1
```

用户并不需要：

```text
1
1
```

而是：

```text
2
```

因此 Brain 需要进行：

```text
1 + 1
    ↓
2
```

这个 `2` 是一个 Derived Result。

然后：

```text
Presentation:
    type = text
    source = derived_result
```

最终 Endpoint 得到：

```text
“现在房子里有 2 个人。”
```

这里：

```text
1 / 1
```

是 Execution Results。

```text
2
```

是 Derived User-facing Result。

```text
text
```

是 Presentation。

---

# 15. Endpoint 的实现责任

Home Agent 只定义 Presentation Protocol。

Endpoint 自己负责具体实现。

例如 Kindle：

```text
Presentation:
    type = html
```

Kindle Endpoint：

```text
HTML Renderer
    ↓
Kindle Browser
```

如果：

```text
Presentation:
    type = image
```

Kindle 自己负责：

```text
Image Renderer
    ↓
Kindle Display
```

如果：

```text
Presentation:
    type = text
```

Kindle 自己负责：

```text
Text Renderer
    ↓
Kindle Display
```

因此：

> **Brain 负责决定“给什么”，Endpoint 负责决定“怎么呈现”。**

Endpoint 不应该要求 Brain 理解它内部的渲染实现。

---

# 16. Observer

## 16.1 Definition

Observer 是能够消费 Home Agent 系统事件、状态或信息流，但不参与当前任务执行和用户结果交付的 Participant。

它回答：

> **“我想知道 Home Agent 发生了什么。”**

Observer 不一定：

* 产生 Intent
* 执行 Capability
* 接收 Presentation

因此 Observer 可以独立存在。

---

# 17. Observer 与 Endpoint 的区别

Endpoint 消费：

```text
Presentation
```

Observer 消费：

```text
System Events / State Stream
```

例如：

```text
Endpoint:
    “把照片给我。”

Observer:
    “告诉我刚才发生了什么。”
```

因此：

```text
Home Agent
├── Presentation Flow
│      ↓
│   Endpoint
│
└── Event / State Flow
       ↓
    Observer
```

---

# 18. Observer Example：CLI

CLI 可以注册为：

```text
Participant:
    mac_cli_xxx

Role:
    Observer
```

然后观察：

```text
intent.created
task.created
step.started
step.completed
runtime.connected
runtime.disconnected
presentation.created
task.completed
task.failed
```

CLI 可以显示：

```text
[14:32:01] Intent received
[14:32:02] Plan created
[14:32:03] camera.take_photo started
[14:32:05] camera.take_photo succeeded
[14:32:06] Presentation resolved
[14:32:06] Endpoint: iphone.display
[14:32:07] Task completed
```

CLI 并没有参与任务本身。

它只是旁观者。

---

# 19. Observer Example：Web Dashboard

Web Dashboard 可以作为 Observer Participant。

```text
Web Dashboard
    ↓
Observer
    ↓
Event Stream
    ↓
Home Agent
```

Dashboard 可以观察：

* 新 Intent
* Task 状态
* Step 状态
* Runtime 状态
* Endpoint 状态
* Presentation 状态
* Participant 在线状态
* Capability 执行情况
* 错误和失败

因此 Web Dashboard 不需要被定义成一个 Endpoint。

它首先是一个：

> **Information Flow Consumer**

也就是系统信息流的消费者。

---

# 20. Participant Registration

Home Agent 中所有参与系统的实体都应通过 Participant Registration 声明自己的身份和角色。

概念上：

```text
Participant Registration
├── Identity
├── Intent Sources
├── Runtime Agents
├── Endpoints
└── Observers
```

其中每一项都是可选的。

---

# 21. Example：Kindle

```text
Participant
    identity:
        kindle_xxx

Roles:
    Endpoint

Endpoints:
    kindle_browser

Supported Presentation:
    html
    text
    image
```

Kindle：

* 不是 Intent Source
* 不执行 Runtime Capability
* 是 Endpoint
* 可以接收 Home Agent Presentation

---

# 22. Example：GoPro

```text
Participant
    identity:
        gopro_xxx

Roles:
    Runtime Agent

Capabilities:
    camera.take_photo
```

GoPro：

* 不是 Intent Source
* 不一定是 Endpoint
* 是 Runtime
* 为 Home Agent 执行 Camera Capability

---

# 23. Example：iPhone

iPhone 可以同时承担多个角色：

```text
Participant
    identity:
        iphone_xxx

Roles:
    Intent Source
    Runtime Agent
    Endpoint
    Observer
```

例如：

```text
Intent Source:
    microphone

Runtime:
    gopro.take_photo
    gopro.download_photo

Endpoints:
    display
    speaker

Observer:
    optional event subscription
```

于是此前容易产生混淆的：

> “iPhone 到底是输入、输出还是 GoPro Runtime？”

现在不再是一个问题。

答案是：

> **它是同一个 Participant，同时声明了多个 Role。**

---

# 24. Role Composition

Role 不应被设计成互斥枚举。

正确模型：

```text
Participant
    ├── Role A
    ├── Role B
    └── Role C
```

例如：

```text
iPhone
├── Intent Source
├── Runtime
└── Endpoint
```

而不是：

```text
iPhone = Intent Source
```

或者：

```text
iPhone = Runtime
```

设备类型不决定 Role。

Participant 注册时声明 Role。

---

# 25. Home Agent Protocol

一旦 Participant 加入 Home Agent，它就必须遵循 Home Agent 定义的协议。

这意味着：

> **参与 Home Agent 的不是“设备本身”，而是遵循 Home Agent Protocol 的 Participant。**

不同 Role 遵循不同 Contract：

```text
Intent Source
    → Intent Contract

Runtime Agent
    → Capability / Execution Contract

Endpoint
    → Presentation Contract

Observer
    → Observation / Event Contract
```

Home Agent 负责定义这些 Contract。

Participant 负责实现这些 Contract。

---

# 26. Protocol Boundary

Home Agent 不应该规定 Participant 的内部实现。

例如：

```text
Home Agent
    ↓
Presentation type = image
```

Kindle 可以使用：

```text
Browser
```

iPhone 可以使用：

```text
Native UI
```

TV 可以使用：

```text
WebView
```

而 Speaker 可以使用：

```text
Audio Player
```

Home Agent 只关心：

```text
Contract
    ↓
Supported Type
    ↓
Protocol Compliance
```

而不关心：

```text
Internal Implementation
```

---

# 27. Unified Architecture

最终 Home Agent 的整体模型可以统一成：

```text
                         Home Agent
                              │
                         Participant
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ↓                ↓                ↓
       Intent Source       Runtime          Endpoint
             │                │                │
          Intent         Capability       Presentation
             │                │                │
             └───────────────┼────────────────┘
                             ↓
                           Brain
                             │
                      Execution Planning
                             │
                             ↓
                          Runtime
                             │
                             ↓
                     Execution Results
                             │
                             ↓
                  Presentation Resolution
                             │
                             ↓
                        Presentation
                             │
                             ↓
                          Endpoint


                  ─────────────────────

                         Event Stream
                              │
                              ↓
                          Observer
```

---

# 28. Core Architectural Principles

## Principle 1 — Device is not Role

设备不是系统中的核心角色。

Participant 才是。

Device 只是 Participant 的一种承载方式。

---

## Principle 2 — Roles are composable

一个 Participant 可以同时承担多个 Role。

例如：

```text
iPhone
    Intent Source
    Runtime
    Endpoint
    Observer
```

---

## Principle 3 — Capability and Presentation are independent

Capability：

> **产生结果。**

Presentation：

> **把结果变成用户真正需要的结果。**

Endpoint：

> **呈现结果。**

---

## Principle 4 — Execution Result is not automatically User-facing Result

Runtime 产生的结果只是 Execution Context 的一部分。

Brain 必须根据 Intent 决定：

* 哪些结果相关；
* 哪些结果需要组合；
* 是否需要计算；
* 最终用户需要什么形式。

然后生成 Presentation。

---

## Principle 5 — Endpoint declares its contract

Endpoint 不需要告诉 Brain 自己内部如何实现。

Endpoint 只需要声明：

> **我支持哪些 Presentation 类型。**

Brain 根据 Presentation Requirement 和 Endpoint Contract 进行匹配。

---

## Principle 6 — Observer consumes system information

Observer 不需要参与 Intent、Execution 或 Presentation。

它可以只消费：

```text
Event
State
Status
Log
```

因此 Web Dashboard、CLI、监控系统、管理工具都可以自然成为 Observer。

---

## Principle 7 — All Participants follow Home Agent Protocol

无论 Participant 是：

* Intent Source
* Runtime
* Endpoint
* Observer

只要参与 Home Agent，就必须遵循对应的 Home Agent Protocol。

这样系统可以保持统一的：

* Identity
* Registration
* Discovery
* Communication
* Event
* Permission
* Lifecycle
* Role Contract

---

# 29. Final Mental Model

Home Agent 最终不是：

```text
Device → Device → Device
```

也不是：

```text
Input Device → Brain → Output Device
```

而是：

```text
                    Participant
                         │
              ┌──────────┼──────────┐
              │          │          │
             Input     Execute     Output
              │          │          │
         Intent Source Runtime   Endpoint
              │          │          │
              └──────────┼──────────┘
                         │
                       Brain
                         │
                    Result Resolution
                         │
                    Presentation
                         │
                      Endpoint

                         +

                      Observer
                         │
                    Event Stream
```

最核心的抽象是：

> **Participant 是加入 Home Agent 的统一主体；Role 定义 Participant 在系统中的行为；Contract 定义该 Role 如何与 Home Agent 协作。**

因此：

> **iPhone 不是“一个输入设备”，也不是“一个输出设备”，更不是“一个 GoPro 控制节点”。它是一个 Participant，只是同时声明了 Intent Source、Runtime、Endpoint 等多个 Role。**

这就是 Home Agent Participant Model 的核心。

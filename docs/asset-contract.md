> 固化自 `/Users/gaolei/devspace/home-agent-docs/home_agent_assets_design.txt`（2026-08-18）。
>
> **命名不要混：** 文中 Runtime / Bridge / Capability / Asset Manager 是产品层。Cursor handle 仍是 `@runtime`（调度/hydrate/Asset Manager 落地）、`@capability`（plugin 契约）、`@brain`（规划/presentation）。没有 Bridge Agent 会话。一期未点名不改代码。
>
> 与 [`participant-model.md`](participant-model.md) 正交：Participant 是谁；Asset 是流转的资源。

可以。这个我建议不要写成“Asset 的技术说明”，⽽是直
接 写 成 ⼀ 份 Asset Contract / Design Convention ， 让
Runtime Agent、Capability Agent、Bridge Agent 以及以后
所有接⼊ Asset 的 Agent 都把它当成上层接⼝公约。
我会把我们之前讨论过的原则统⼀起来，并且明确哪些
事情 Agent 不允许⾃⼰重新定义。
Asset Contract & Design Convention
Status: Design Convention
Scope: Home Agent Runtime / Bridge / Capability / Asset
Manager / Edge Node
Purpose: 为所有 Agent 提供统⼀的 Asset 抽象、访问⽅
式、权限模型和交互契约。
⸻
1. Design Goal
Asset 是 Home Agent Runtime 中对“可被系统产⽣、保存、
访问、传递和消费的数据资源”的统⼀抽象。
Asset 的⽬的不是简单封装⼀个⽂件，⽽是：
让上层 Intent / Task / Capability 不需要知道数据实际存
在哪⾥、如何存储、如何传输、如何授权访问。
因此：
* Capability 不应该直接操作 filesystem。
* Capability 不应该依赖固定 URL。
* Capability 不应该⾃⾏管理 Asset storage。
* Capability 不应该⾃⾏实现 Asset permission。
* Intent / Task 不应该携带⼤块⼆进制数据。
* Runtime 不应该把某⼀种 storage provider 的细节暴露
给 Capability。
统⼀通过 Asset Contract 完成。
⸻
2. Core Principle
2.1 Asset 是资源，不是⽂件
以下对象都可以成为 Asset：
* image
* video
* audio
* document
* text
* generated content
* sensor data
* model input/output
* future arbitrary binary data
因此：
Asset
├── image
├── video
├── audio
├── document
├── text
├── url   （内容=目标 http(s) 链接；经 POST /api/v1/assets/register 无字节登记）
└── other
不能把 Asset 定义成：
Asset = File
正确理解应该是：
Asset = Runtime-managed Resource
File 只是 Asset 的⼀种 physical representation。
⸻
3. Asset Identity
每⼀个 Asset 必须具有稳定的 Asset Identity。
推荐：
asset_id
Asset ID 是 Runtime 内部引⽤ Asset 的主要⽅式。
例如：
{
"asset_id": "asset_01J...",
"type": "image"
}
上层系统应该传递：
asset_id
⽽不是：
/path/to/image.jpg
也不应该把：
https://...
作为 Asset 的 canonical identity。
⸻
4. Asset Reference
在 Intent、Task、Capability Input、Execution Result 中，
如果需要引⽤⼀个 Asset，应使⽤ Asset Reference。
例如：
{
"asset_id": "asset_xxx",
"type": "image"
}
Asset Reference 的意义是：
“这⾥引⽤了⼀个由 Runtime 管理的资源。”
⽽不是：
“这⾥有⼀个 URL，你⾃⼰去下载。”
⸻
5. Storage Must Be Transparent
Asset 的实际存储位置不是 Contract 的⼀部分。
Asset 可能存在于：
Local filesystem
Object storage
Edge Node
Mac
iPhone
Camera device
Cloud storage
Temporary storage
Memory
甚⾄同⼀个 Asset 在⽣命周期内可以发⽣ storage
migration。
例如：
Camera
↓
Edge Node local storage
↓
Runtime Asset Manager
↓
Object Storage
上层 Capability 不应该关⼼这个过程。
因此禁⽌：
open("/some/internal/path")
作为 Asset 的标准访问⽅式。
⸻
6. URL Is NOT Asset Identity
这是 Asset Contract 中⾮常重要的⼀条。
不能设计：
{
"asset": {
"url": "https://..."
}
}
然后让所有 Capability 依赖 URL。
原因：
1. URL 可能过期。
2. URL 可能需要权限。
3. URL 可能只适⽤于某⼀个⽹络环境。
4. URL 可能对应某⼀种 representation。
5. Asset 可能根本没有公⽹ URL。
6. Runtime 可能需要把 Asset 从⼀个 Node 转移到另⼀
个 Node。
因此：
Asset ID
↓
Asset Manager
↓
Access / Representation
↓
URL / Stream / Local File / Bytes
⽽不是：
URL
↓
Asset
⸻
7. Representation
⼀个 Asset 可以拥有多种 Representation。
例如⼀个图⽚ Asset：
Asset
├── original
├── thumbnail
├── compressed
├── local file
├── stream
└── temporary signed URL
因此：
Asset 是逻辑资源，Representation 是访问这个资源的⼀
种具体形式。
例如：
asset_123
可以根据调⽤⽅需要得到：
download
stream
temporary_url
local_path
bytes
但这些都不是 Asset 本身。
⸻
8. Asset Access
Capability 应该通过 Runtime 提供的 Asset API 访问资
源。
推荐抽象：
asset.get()
asset.download()
asset.stream()
asset.metadata()
asset.request_access()
实际 SDK 名称可以根据语⾔调整，但语义必须保持⼀
致。
⸻
9. download()
download() 表示：
将 Asset 以适合本地处理的形式获取到当前 Runtime /
Capability 所在环境。
例如：
path = asset.download()
Capability 得到的是：
local representation
⽽不是 Asset 本身。
Capability 可以使⽤这个 local representation 调⽤：
* OCR
* FFmpeg
* Image Processing
* ML Model
* Computer Vision
* etc.
Capability 不需要知道 Asset 原本在哪⾥。
⸻
10. stream()
对于视频、⾳频以及未来的实时数据，不能强制所有场景
都 download()。
因此应该⽀持：
stream = asset.stream()
例如：
GoPro
↓
Video Asset
↓
Asset Manager
↓
Capability
↓
FFmpeg / Decoder
这对于：
* video
* audio
* live media
* large files
尤其重要。
⸻
11. Temporary URL
某些第三⽅⼯具只能接受 URL。
例如：
FFmpeg
Browser
Chromecast
External API
这时 Asset Manager 可以⽣成：
temporary signed URL
例如：
url = asset.get_access_url(ttl=300)
但这个 URL：
* 是临时的
* 有权限边界
* 可以过期
* 不是 Asset identity
* 不应该被⻓期保存为 Asset metadata
正确关系：
Asset
↓
Access Request
↓
Temporary URL
⽽不是：
Asset
↓
Permanent URL
⸻
12. Asset Metadata
Asset 可以拥有 metadata。
例如：
{
"asset_id": "asset_xxx",
"type": "image",
"mime_type": "image/jpeg",
"size": 1234567,
"created_at": "...",
"width": 1920,
"height": 1080
}
Metadata ⽤于描述 Asset。
Metadata 不应该包含依赖某个 storage provider 的内部
实现细节。
例如不应该把：
{
"s3_bucket": "...",
"internal_path": "..."
}
作为公开 Asset Contract。
⸻
13. Asset Manager
Runtime 应该存在⼀个统⼀的：
Asset Manager
Asset Manager 是 Asset 的主要控制⼊⼝。
它负责：
1. Asset registration
2. Asset identity
3. metadata
4. storage abstraction
5. access control
6. representation generation
7. download
8. stream
9. temporary URL
10. lifecycle
11. cleanup
12. cross-node access
架构：
┌─────────────────┐
│ Capability │
└────────┬────────┘
│
Asset SDK / API
│
┌────────▼────────┐
│ Asset Manager │
└────────┬────────┘
│
┌─────────────┼──────────
───┐
↓ ↓ ↓
Local Storage Edge Node Object Storage
Capability 不应该绕过 Asset Manager。
⸻
14. Asset Creation
Asset 可以由不同 Runtime Component 创建。
例如：
Camera Capability
Microphone Capability
GoPro Capability
OCR Capability
LLM Capability
File Capability
统⼀流程：
Producer
↓
Asset Manager.create/register
↓
Asset ID
↓
Execution Result
例如 Camera Capability：
Camera
↓
capture
↓
Asset Manager
↓
asset_id
Capability 返回：
{
"asset_id": "asset_xxx"
}
⽽不是：
{
"file_path": "/tmp/image.jpg"
}
⸻
15. Asset Lifecycle
Asset 应具有明确⽣命周期。
典型⽣命周期：
CREATED
↓
AVAILABLE
↓
IN_USE
↓
ARCHIVED
↓
EXPIRED / DELETED
具体状态可以根据 Runtime 实现调整，但⽣命周期必须
由 Asset Manager 管理。
Capability 不应该⾃⾏删除 Asset，除⾮ Contract 明确允
许。
⸻
16. Temporary Assets
很多 Capability 产⽣的 Asset 只是中间结果。
例如：
Camera capture
↓
Image Asset
↓
OCR
↓
Text
其中 Image 可能只需要存在⼏分钟。
因此 Asset 应⽀持：
TTL
expiration
temporary lifecycle
例如：
{
"asset_id": "asset_xxx",
"lifecycle": {
"expires_at": "..."
}
}
这样 Runtime 可以⾃动清理临时资源。
⸻
17. Asset Permission
Asset 必须具备访问控制。
关键原则：
拥有 Asset ID 不等于拥有 Asset 的读取权限。
也就是说：
asset_id
只是 identity/reference。
真正访问 Asset 需要：
Authorization
⸻
18. Execution-scoped Access
我们之前确定的⼀个核⼼原则是：
Asset Access 应该尽可能绑定到当前 Execution，⽽不是
永久绑定给 Capability。
关系：
Intent
↓
Execution
↓
Capability
↓
Asset Access
例如：
Intent #123
↓
Execution #456
↓
OCR Capability
↓
read Asset #789
OCR Capability 不因此获得：
永久读取 Asset #789
⸻
19. Access Grant
Runtime 可以在 Execution 开始后，为 Capability 创建
临时 Access Grant。
例如概念模型：
{
"asset_id": "asset_xxx",
"execution_id": "execution_xxx",
"capability_id": "ocr",
"permission": "read",
"expires_at": "..."
}
这样可以实现：
Execution-scoped authorization
⽽不是：
Capability permanently owns asset
⸻
20. Permission Types
⾄少应该区分：
read
write
append
stream
share
delete
第⼀阶段可以只实现：
read
write
但 Contract 不应该把模型限制死。
⸻
21. Access Request
Capability 如果需要 Asset，⽽ Runtime 没有提前授权，
可以通过：
request_access()
表达需求。
例如：
asset.request_access(
permission="read"
)
Runtime 决定：
ALLOW
DENY
WAIT
这⾥和系统已有的 Intent / Execution 状态模型可以⾃然
结合。
⸻
22. WAIT / Micro-pause
如果 Asset 访问需要进⼀步的⽤户确认，不能把它简单
当成 failure。
例如：
Capability wants access
↓
User confirmation required
↓
WAITING
↓
User approves
↓
Execution continues
这和我们之前定义的：
waiting / 微停
是⼀致的。
因此：
permission denied
和：
permission pending
必须区分。
⸻
23. Cross-Node Asset
Home Agent 是分布式 Runtime。
因此 Asset 可能产⽣于：
GoPro
但最终被：
Mac
处理。
或者：
iPhone
产⽣ Asset，
然后：
Mac OCR Capability
消费它。
因此：
Producer Node
↓
Asset Manager
↓
Asset Reference
↓
Consumer Node
↓
Asset Access
Consumer 不应该⾃⼰处理：
GoPro IP
WiFi
filesystem path
HTTP endpoint
这些都应该由 Runtime / Asset Manager 隐藏。
⸻
24. Example: Camera → OCR
这是⼀个典型流程。
Camera Capability
│
│ capture
▼
Asset Manager
│
│ asset_id
▼
Execution Result
│
▼
OCR Capability
│
│ asset.download()
▼
Local Representation
│
▼
OCR Engine
│
▼
Text Result
⽽不是：
Camera
↓
/tmp/a.jpg
↓
OCR reads /tmp/a.jpg
⸻
25. Example: GoPro → FFmpeg
GoPro 产⽣视频：
GoPro
↓
Video Stream / Video Asset
↓
Asset Manager
↓
FFmpeg Capability
FFmpeg 可以根据需要：
asset.download()
或者：
asset.stream()
如果 FFmpeg 只能接受 URL：
asset.get_access_url()
三种⽅式都指向：
同⼀个 Asset
⸻
26. Example: Reading Agent
Reading Agent 的摄像头拍到书⻚：
Camera
↓
Image Asset
↓
Asset Manager
↓
Vision / OCR Capability
↓
Character Recognition
↓
Result
如果需要 Kindle / Display 展示处理后的图⽚：
Image Asset
↓
Display Capability
↓
Asset Access
Display 不应该要求：
某个固定 HTTP URL
⽽应该接受：
Asset Reference
然 后 由 Runtime 为 它 提 供 适 合 Display 的
representation。
⸻
27. Asset vs Result
必须区分：
Asset
和：
Execution Result
Asset 是资源。
Result 是⼀次执⾏产⽣的结构化结果。
例如：
{
"result": {
"text": "你好"
},
"assets": [
{
"asset_id": "asset_image_123"
}
]
}
不要把：
Asset
和：
混为⼀谈。
⸻
28. Asset vs Capability
Capability 是：
能做什么
Asset 是：
例如：
OCR Capability
+
Image Asset
↓
Text Result
因此 Capability Contract 应该声明：
input:
image asset
output:
text
⽽不是规定：
input:
local jpg path
⸻
29. Asset API Design Rule
任何新的 Capability，如果需要处理资源，应优先设计：
Asset Reference
作为输⼊。
例如：
{
"input": {
"asset_id": "asset_xxx"
}
}
⽽不是：
{
"input": {
"url": "...",
"path": "..."
}
}
如 果 Capability 确 实 需 要 具 体 representation ， 由
Capability Runtime SDK 获取。
⸻
30. Forbidden Patterns
以下设计原则上禁⽌：
30.1 Capability 直接读取 Runtime storage
open("/runtime/assets/xxx")
禁⽌。
⸻
30.2 Capability ⾃⼰拼 URL
url = "http://mac:8080/assets/" + asset_id
禁⽌。
⸻
30.3 Asset 以 permanent URL 为 identity
{
"asset": {
"url": "https://..."
}
}
禁⽌。
⸻
30.4 Capability 永久保存 Asset access token
禁⽌。
Access token / signed URL 应具有明确 TTL。
⸻
30.5 Capability ⾃⼰决定 Asset 权限
Capability 可以：
request
但最终 authorization 应由 Runtime / Asset Manager 决定。
⸻
30.6 Intent 携带⼤⽂件
禁⽌：
{
"image": "<base64 huge data>"
}
应该：
{
"asset_id": "asset_xxx"
}
⸻
31. SDK Abstraction
推荐 SDK 向 Capability 暴露：
AssetRef
AssetManager
AssetAccess
概念接⼝：
class AssetRef:
id: str
type: str
def metadata(self):
...
def download(self):
...
def stream(self):
...
def get_access_url(self, ttl=None):
...
def request_access(self, permission):
...
具体语⾔和实现可以变化。
但语义不能变化。
⸻
32. Asset Manager Interface
概念上：
class AssetManager:
def create(self, type, metadata=None):
...
def register(self, source, metadata=None):
...
def get(self, asset_id):
...
def delete(self, asset_id):
...
def grant_access(self, asset_id, execution_id,
permission):
...
def request_access(self, asset_id, execution_id,
permission):
...
这只是 Contract 的参考接⼝。
具体 implementation 可以根据 Runtime 架构调整。
⸻
33. Producer / Consumer Contract
任何 Asset ⽣产者必须：
produce → register → return Asset Reference
任何 Asset 消费者必须：
receive Asset Reference
↓
request/access Asset
↓
obtain representation
↓
process
形成统⼀的数据流：
Producer
↓
Asset Manager
↓
Asset Reference
↓
Consumer
↓
Representation
↓
Processing
⸻
34. Ownership
Asset 的：
creator
owner
consumer
必须概念上区分。
Capability 创建 Asset：
creator = camera capability
不代表：
camera capability owns the Asset forever
Asset 的⽣命周期和权限由 Runtime 管理。
⸻
35. Asset Sharing
如果⼀个 Asset 需要被多个 Capability 使⽤：
Asset
├── OCR Capability
├── Vision Capability
└── Display Capability
应该由 Runtime 分别授予 access。
⽽不是把 Asset 复制成：
asset_for_ocr
asset_for_vision
asset_for_display
除⾮实际 representation 确实发⽣变化。
⸻
36. Asset Copy vs Reference
默认：
pass Asset Reference
只有在以下情况才应该真正 copy：
* 跨存储系统迁移
* 跨 Node 缓存
* representation conversion
* isolation requirement
* explicit user request
因此：
Reference passing
应该是默认机制。
⸻
37. Asset Transformation
Capability 对 Asset 进⾏转换时，应产⽣新的 Asset。
例如：
original image
↓
resize
↓
new image Asset
不要隐式修改原 Asset。
例如：
asset_A
↓ resize
asset_B
⽽不是：
asset_A
↓
overwrite
asset_A
这样可以保证：
* provenance
* reproducibility
* debugging
* caching
* permission isolation
⸻
38. Provenance
如果 Asset 是由另⼀个 Asset ⽣成的，应尽量保留
provenance。
例如：
asset_A
↓
OCR
↓
asset_B
可以记录：
source_asset = asset_A
producer = OCR Capability
execution_id = execution_xxx
这对于后续：
* debugging
* audit
* trace
* asset lineage
⾮常重要。
⸻
39. Asset Error Model
Asset 相关错误不要统⼀叫：
FAILED
⾄少应区分：
NOT_FOUND
ACCESS_DENIED
ACCESS_PENDING
EXPIRED
UNAVAILABLE
INVALID_REFERENCE
TRANSFER_FAILED
REPRESENTATION_UNAVAILABLE
尤其：
ACCESS_PENDING
应该能够进⼊：
WAITING
⽽不是直接导致整个 Intent failure。
⸻
40. Runtime Boundary
Asset Contract 的边界应该是：
Runtime
┌─────────────────────────────────
────────┐
│ │
│ Intent / Task │
│ │ │
│ ▼ │
│ Scheduler / Dispatcher │
│ │ │
│ ▼ │
│ Capability │
│ │ │
│ ▼ │
│ Asset SDK │
│ │ │
│ ▼ │
│ Asset Manager │
│ │ │
│ ├──── Local Storage │
│ ├──── Edge Node │
│ ├──── Object Storage │
│ └──── Temporary Representation │
│ │
└─────────────────────────────────
────────┘
Capability 只能看到：
Asset Contract
不应该看到：
Storage implementation
Network topology
Internal filesystem
Provider credentials
Permanent URLs
⸻
41. Design Principle for All Agents
以后任何 Agent 设计涉及以下内容：
image
video
audio
file
document
stream
attachment
generated media
camera output
microphone output
必须⾸先问：
“这个东⻄是不是应该成为 Asset？”
如果答案是 Yes：
使⽤ Asset Contract，不要重新设计⼀套⾃⼰的 File /
URL / Attachment 接⼝。
⸻
42. Agent Implementation Rules
所有 Agent 在实现相关接⼝时必须遵循：
Rule 1
Asset ID 是资源身份。
Rule 2
URL 不是资源身份。
Rule 3
Storage 对 Capability 透明。
Rule 4
Capability 通过 Asset SDK 访问资源。
Rule 5
Permission 由 Runtime / Asset Manager 控制。
Rule 6
Access 默认与 Execution 关联。
Rule 7
Temporary URL / token 必须具有⽣命周期。
Rule 8
Intent / Task 传 Asset Reference，不传⼤块数据。
Rule 9
Asset transformation 默认产⽣新 Asset。
Rule 10
跨 Node 传递默认传 Reference，⽽不是⼿⼯传⽂件。
Rule 11
Capability 不允许⾃⾏定义 Asset storage/access protocol。
Rule 12
如果已有 Asset Contract 可以表达需求，不得创建平⾏的
File / Attachment / Media / URL abstraction。
⸻
43. Canonical Data Flow
整个系统应该最终形成这样的统⼀模式：
USER INTENT
│
▼
Intent
│
▼
Task
│
▼
Execution
│
▼
Capability
│
┌───────┴───────┐
│ │
▼ ▼
Input Asset New Asset
│ │
▼ │
Asset Manager ◄───────┘
│
┌─────┼─────┐
▼ ▼ ▼
Local Stream URL
│ │ │
└─────┼─────┘
▼
Capability
│
▼
Result
Asset 在这⾥成为 Runtime 内部连接：
Device
Capability
Execution
Storage
Network
Result
的统⼀资源层。
⸻
44. Final Contract
最终可以把 Asset Contract 压缩成⼀句话：
Asset is a Runtime-managed resource identified by an Asset
ID. Capabilities consume and produce Asset References,
while the Runtime owns storage, access control, lifecycle,
and representation.
中⽂：
Asset 是由 Runtime 管理的资源，以 Asset ID 作为唯⼀
引⽤。Capability 只⽣产和消费 Asset Reference；资源的
存储、权限、⽣命周期以及具体访问形式由 Runtime 统
⼀负责。
这应该作为所有 Agent 设计 Asset 相关接⼝时的最⾼
层原则。
⸻
45. Implementation Priority
第⼀阶段不需要⼀次实现所有⾼级能⼒。
推荐最低可⽤ Contract：
Asset ID
↓
Asset metadata
↓
Asset Manager
↓
get()
download()
第⼆阶段：
stream()
temporary URL
TTL
第三阶段：
Execution-scoped permission
Access Grant
Cross-node transfer
第四阶段：
Provenance
Transformation lineage
Advanced lifecycle
Multiple representations
但是：
即使第⼀阶段只实现 asset_id + download()，接⼝也必须
按照完整 Asset Contract 设计。
不要为了第⼀版简单，⽽把 file_path 或 url 做成未来⽆
法兼容的核⼼接⼝。
⸻
46. Agent Review Checklist
任何 Agent 提交 Asset 相关接⼝前，都必须检查：
* 是否使⽤ asset_id 作为资源引⽤？
* 是否避免把 URL 当成 Asset identity？
* 是否避免暴露 filesystem path？
* 是否通过 Asset Manager / SDK 访问？
* 是否明确 Asset 是 input 还是 output？
* 是否需要 access permission？
* permission 是否绑定 Execution？
* temporary URL / token 是否有 TTL？
* 是否避免把 Asset ⼆进制直接塞进 Intent / Task？
* 是否正确处理跨 Node 场景？
* 是否区分 Asset 和 Execution Result？
* Asset transformation 是否产⽣新 Asset？
* 是否记录必要的 provenance？
* 是 否 正 确 区 分 ACCESS_DENIED /
ACCESS_PENDING / NOT_FOUND？
* 是 否 重 复 创 建 了 已 有 的 File / URL / Attachment
abstraction？
如果其中任何⼀项违反 Contract，需要在设计 review 中
说明原因。
⸻
47. Architectural Intent
Asset Contract 最终要解决的不是“怎么存⼀张图⽚”。
它解决的是 Home Agent 作为⼀个分布式 Runtime 以后，
所有数据资源如何在：
Device
↕
Edge Node
↕
Runtime
↕
Capability
↕
Execution
↕
Storage
之间流动的问题。
因此 Asset 应该被视为 Runtime 的基础设施层，⽽不是
某⼀个 Capability 的功能。
任 何 Capability 都 可 以 使 ⽤ Asset ； 但 没 有 任 何
Capability 应该重新定义 Asset。

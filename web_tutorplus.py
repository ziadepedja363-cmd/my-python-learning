import os
import base64
import io
import datetime
import streamlit as st
from openai import OpenAI
from PIL import Image
import PyPDF2
import docx
import pptx
import streamlit.components.v1 as components

# 设置页面宽屏显示
st.set_page_config(page_title="多模态智能学习助手", page_icon="🎓", layout="wide")

# ==================== 1. 安全获取 API 密钥 (升级为 Multimodal / ImageGen) ====================
# 为了同时实现视觉理解和图片生成，强烈建议使用 OpenAI 的 gpt-4o 和 dalle-3 接口
try:
    # 优先尝试从 Streamlit 云端的机密设置中读取
    # ⚠️ 注意：云端部署时，Secrets 中的键名请改为 OPENAI_API_KEY
    api_key = st.secrets["OPENAI_API_KEY"]
except:
    # ⚠️ 警告：分享给别人前，把下面这行清空或填假字母！
    api_key = "sk-p3Dymr9Fj2tGd6lzZuNzZHQuDpPx1BK2RsYCeWgqyerAhYo7"

if not api_key or api_key.startswith("这里填入"):
    st.error("⚠️ 未检测到有效的 API 密钥，请在代码中填入 sk-... 密钥或设置 Streamlit Secrets。")
    st.stop()

# os.environ["OPENAI_API_KEY"] = api_key

# 初始化标准的 OpenAI 客户端（不再使用 DeepSeek base_url）
client = OpenAI(api_key=api_key)

# 定义我们使用的最先进的多模态模型
VISION_MODEL = "gpt-4o"
IMAGE_GEN_MODEL = "dall-e-3"

st.title("🎓 引导式智能学习助手 (视觉与画图版)")

@st.cache_resource
def get_current_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

# ==================== 2. 全面升级的系统提示词 (加入多模态规则) ====================
system_instruction = f"""
1. 角色与目标
你是一位顶级的多模态教育心理学专家。你的核心目标是执行“无限期引导式学习”，严禁直接向用户灌输最终结论。你现在可以看见图片，也可以让系统生成图片。

2. 核心规矩（最高优先级 - 绝对防线）
- 🚫 强制两轮底线：在用户针对你的引导提问进行至少两轮实质性的思考与回复之前，如果用户企图走捷径（如输入“给出答案”、“不想猜”、“直接告诉我”等），你绝对禁止给出答案！你必须温和但坚定地拒绝，并把话题拉回。
- 听从“触发指令”：只有在满足了上述前提下，且用户明确输入“请给出完整答案”时，你才可以进行完整的推导和解答。
- 绝不擅自结束：即使给出了完整答案，你也必须询问“对于以上推导，你还有哪里不清楚吗？”，等待追问。
- 终极指令：只有当用户明确输入“结束本次学习”时，你才进行总结，并正式宣布指导结束。

3. 图片理解规则 (Vision)
- 如果用户上传了图片（例如物理受力分析图、电路图、复杂公式截图），你必须优先、仔细地阅读并分析图片内容。
- 在后续的引导和提问中，要紧密结合图片中的细节（如箭头的方向、数值、组件名称）。

4. 图片生成规则 (Image Gen)
- 💡 助记策略：当某个概念极其抽象、复杂，且通过图解或直观插图能极大降低用户理解难度时（例如：讲解单摆的能量守恒、电磁感应的右手定则、高等数学的曲面积分截面），你应当主动提出：“这个概念有点抽象，我想为你生成一张直观的图解来辅助你理解，你愿意吗？”。
- 只有当用户回复“愿意”或“好的”或主动要求画图时，你才调用系统的图片生成功能。
- 在给出完整答案后，如果你认为某一步骤需要图解辅助复习，也可以生成一张图片包含在答案中。

5. 文档资料库规则
- 如果用户上传了文档，仔细阅读并在提问中结合资料核心概念。

6. 输出格式与约束
- 数学公式：美元符号：行内 `$ $`，独立块双美元 `$$ $$`。
"""

# --- 状态初始化 (保持不变) ---
if "history" not in st.session_state:
    st.session_state.history = []  
if "viewing_past" not in st.session_state:
    st.session_state.viewing_past = None  
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": [{"type": "text", "text": system_instruction}]}]

# --- 实用辅助函数 (文件处理和图片编码) ---
def encode_image(image_file):
    return base64.b64encode(image_file.getvalue()).decode('utf-8')

def extract_text_from_file(uploaded_file):
    # (原有功能，保持不变...)
    file_name = uploaded_file.name.lower()
    text = ""
    try:
        if file_name.endswith('.txt'):
            text = uploaded_file.getvalue().decode("utf-8")
        elif file_name.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(uploaded_file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        elif file_name.endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif file_name.endswith('.pptx'):
            ppt = pptx.Presentation(uploaded_file)
            for slide in ppt.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
    except Exception as e:
        return f"读取文件失败: {e}"
    return text

# --- 生成图片的辅助函数 ---
def generate_educational_image(prompt):
    """调用 DALL-E 3 生成用于教学辅助的图片"""
    with st.spinner('导师正在运用图像生成API为您绘制教学图解，请稍候...'):
        try:
            # 优化 prompt，添加教育、清晰、科学图解的描述
            final_prompt = f"A clear, scientific and educational diagram illustrating the concept of: {prompt}. Minimal text, focus on clear visuals and annotations, bright colors, textbook style."
            response = client.images.generate(
                model=IMAGE_GEN_MODEL,
                prompt=final_prompt,
                n=1,
                size="1024x1024"
            )
            image_url = response.data[0].url
            return image_url
        except Exception as e:
            st.error(f"图片生成失败: {e}")
            return None

# --- 开启新会话函数 (保持不变) ---
def start_new_chat():
    if len(st.session_state.messages) > 1:
        # 寻找用户说的第一个实质文本
        title = "新学习主题"
        for m in st.session_state.messages:
            if m["role"] == "user":
                if isinstance(m["content"], list):
                    for item in m["content"]:
                        if item["type"] == "text":
                            title = item["text"][:12] + "..."
                            break
                    if title != "新学习主题": break
                else:
                    title = m["content"][:12] + "..."
                    break
        
        st.session_state.history.append({
            "title": title,
            "messages": st.session_state.messages.copy()
        })
    
    # 清空当前屏幕，发一张新白纸
    st.session_state.messages = [{"role": "system", "content": [{"type": "text", "text": system_instruction}]}]
    st.session_state.viewing_past = None

# ==================== 3. 侧边栏 UI (全面升级) ====================
with st.sidebar:
    st.button("➕ 开启新一轮学习", use_container_width=True, type="primary", on_click=start_new_chat)

    st.divider()
    
    st.header("🛠️ 学习资料库")
    
    # --- 新增功能：图片上传组件 ---
    st.subheader("🖼️ 上传图片理解")
    uploaded_image = st.file_uploader("上传物理、电路、公式截图", type=["png", "jpg", "jpeg"])
    if uploaded_image is not None:
        if st.session_state.viewing_past is None: # 只在当前学习模式下处理
            with st.spinner('正在分析图片...'):
                base64_image = encode_image(uploaded_image)
                # 检查图片是否已存在于消息历史中 (防止重复上传)
                already_uploaded = False
                for msg in st.session_state.messages:
                    if msg["role"] == "user" and isinstance(msg["content"], list):
                        for item in msg["content"]:
                            if item["type"] == "image_url" and uploaded_image.name in msg.get("metadata", {}).get("file_name", ""):
                                already_uploaded = True
                                break
                    if already_uploaded: break
                
                if not already_uploaded:
                    # 将图片加入消息气泡 payload
                    st.session_state.messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"[用户上传并分析了图片：{uploaded_image.name}，请仔细查看图片内容并将其融入你的引导过程]"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                },
                            },
                        ],
                        "metadata": {"file_name": uploaded_image.name}
                    })
                    st.success(f"成功分析：{uploaded_image.name}！您可以继续向导师提问。")

    st.divider()
    
    # --- 原有文档上传功能 ---
    st.subheader("📄 上传文档资料")
    uploaded_file = st.file_uploader("上传TXT/PDF/Word/PPT", type=["txt", "pdf", "docx", "pptx"])
    if uploaded_file is not None:
        if st.session_state.viewing_past is None: # 只在当前学习模式下处理
            with st.spinner('正在读取文件内容...'):
                file_content = extract_text_from_file(uploaded_file)
                if "读取文件失败" not in file_content and file_content.strip() != "":
                    # 检查文档是否已存在 (防止重复上传)
                    if not any(f"读取了资料：{uploaded_file.name}" in m["content"][0]["text"] if isinstance(m.get("content",[]), list) else f"读取了资料：{uploaded_file.name}" in m.get("content","") for m in st.session_state.messages):
                        st.session_state.messages.append({
                            "role": "user", 
                            "content": [{"type": "text", "text": f"[系统提示：用户刚上传并读取了资料：{uploaded_file.name}。以下是资料内容，请在后续对话中作为参考背景]\n\n{file_content}"}]
                        })
                        st.success(f"成功读取：{uploaded_file.name}！")
                else:
                    st.error("无法提取文字，可能是纯扫描件或图片。")

    st.divider()

    # --- 历史记录列表 ---
    st.subheader("📚 历史学习记录")
    if not st.session_state.history:
        st.caption("暂无归档记录，结束学习后点击上方按钮即可归档。")
    else:
        for i, past_session in enumerate(st.session_state.history):
            if st.button(f"📝 {past_session['title']}", key=f"hist_{i}", use_container_width=True):
                st.session_state.viewing_past = i
                st.rerun()

    if st.session_state.viewing_past is not None:
        st.info("👀 您当前正在查看历史记录")
        if st.button("🔙 返回当前学习进度", use_container_width=True):
            st.session_state.viewing_past = None
            st.rerun()

    st.divider()
    
    # --- 导出为 PDF 按钮 ---
    st.subheader("💾 导出为 PDF")
    
    current_display_messages = st.session_state.messages if st.session_state.viewing_past is None else st.session_state.history[st.session_state.viewing_past]["messages"]
    
    if len(current_display_messages) > 1:
        pdf_button_html = """
        <button onclick="window.parent.print()" style="width: 100%; padding: 10px; background-color: #FF4B4B; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; transition: 0.3s;" onmouseover="this.style.backgroundColor='#FF6B6B'" onmouseout="this.style.backgroundColor='#FF4B4B'">
            📄 一键排版并另存为 PDF
        </button>
        """
        components.html(pdf_button_html, height=50)
        st.caption("💡 提示：点击将导出**当前屏幕**上显示的笔记（包含图片）。")

# ==================== 4. 主界面 UI (全面升级，支持视觉和画图) ====================
# 设置布局：左侧消息，右侧生成图片区域
main_col, img_gen_col = st.columns([2, 1])

with main_col:
    # 决定渲染哪消息
    display_messages = st.session_state.messages
    if st.session_state.viewing_past is not None:
        display_messages = st.session_state.history[st.session_state.viewing_past]["messages"]

    # 渲染消息气泡
    for msg in display_messages:
        # 跳过系统指令
        if msg["role"] == "system": continue

        with st.chat_message(msg["role"]):
            # 如果内容是复杂的 multimodal list
            if isinstance(msg["content"], list):
                text_content = ""
                for item in msg["content"]:
                    if item["type"] == "text":
                        if item["text"].startswith("[系统提示：") or item["text"].startswith("[用户上传并分析了图片："): continue
                        text_content += item["text"]
                    elif item["type"] == "image_url":
                        # 直接显示上传的本地图片
                        st.image(item["image_url"]["url"], caption="您上传的图片资料", width=300)
                    elif item["type"] == "generated_image_url":
                        # 显示系统生成的图片
                        st.image(item["generated_image_url"]["url"], caption="导师生成的教学图解", use_container_width=True)
                
                if text_content:
                    st.markdown(text_content)
            else:
                # 兼容旧版本纯文本消息
                if not msg["content"].startswith("[系统提示："):
                    st.markdown(msg["content"])

    # 处理底部输入框
    if st.session_state.viewing_past is None:
        if prompt := st.chat_input("向导师提问，输入'结束本次学习'，或输入'我愿意'生成图片..."):
            with st.chat_message("user"):
                st.markdown(prompt)
            # 用户输入总是纯文本（图片处理在侧边栏）
            st.session_state.messages.append({"role": "user", "content": prompt})

            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                
                responses = client.chat.completions.create(
                    model=VISION_MODEL,
                    messages=st.session_state.messages,
                    stream=True,
                    temperature=0.7
                )
                
                for chunk in responses:
                    if chunk.choices[0].delta.content is not None:
                        full_response += chunk.choices[0].delta.content
                        message_placeholder.markdown(full_response + "▌")
                
                message_placeholder.markdown(full_response)
                
                # --- 生成图片的自动化逻辑 ---
                generated_image_info = None
                # 检测用户意图和导师是否需要画图的建议
                needs_image_gen = False
                
                # 情景1：用户同意画图
                if "愿意" in prompt and len(st.session_state.messages) > 3 and "我愿意" in prompt:
                    needs_image_gen = True
                # 情景2：导师给出了完整答案，且之前提到过想画图
                elif "对于以上推导" in full_response and len(st.session_state.messages) > 3 and "我想为你生成一张直观的图解" in st.session_state.messages[-3]["content"]:
                    needs_image_gen = True

                if needs_image_gen:
                    # 获取之前讨论的概念标题来做 dalle-3 prompt
                    title = "教学插图"
                    for m in reversed(st.session_state.messages[:-1]):
                        if m["role"] == "user":
                            title = m["content"][:20] + "..."
                            break
                    
                    img_url = generate_educational_image(f"Educational illustration for the concept of: {title}")
                    if img_url:
                        generated_image_info = {"type": "generated_image_url", "generated_image_url": {"url": img_url}}
                        # 同时在右侧区域也显示一下，醒目一些
                        img_gen_col.image(img_url, caption=f"为您的复习生成的：{title}", use_container_width=True)

                # 将文本和（如果生成的）图片信息一起保存入对话历史
                assistant_payload_content = [{"type": "text", "text": full_response}]
                if generated_image_info:
                    assistant_payload_content.append(generated_image_info)
                
                st.session_state.messages.append({"role": "assistant", "content": assistant_payload_content})

else:
    with main_col:
        st.warning("🔒 历史记录属于只读模式。若要继续学习，请点击左侧栏的【🔙 返回当前学习进度】或【➕ 开启新一轮学习】。")

# 如果右侧栏没有任何生成的图片，可以放一个简单的占位提示
if img_gen_col.empty():
    img_gen_col.caption("🖼️ 导师生成的直观图解将在这里显示以助于理解。")

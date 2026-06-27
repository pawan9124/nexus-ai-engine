# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.

==================================== LIVE THOUGHT STREAMING FOR LANGGRAPH ==============
feat(ux): implement live thought streaming for LangGraph agent

- Upgraded `/api/chat` from `.ainvoke()` to `.astream()` with `stream_mode="updates"`.
- Added node-by-node yield statements to expose the Agent's internal execution steps.
- Updated frontend UI to properly render newline characters and markdown formatting.

============================= ## 🔹 External API Integration & Alignment Override ====================
## 🔹 External API Integration & Alignment Override
The architecture supports real-time data fetching by allowing the Agent to execute outbound HTTP requests to external APIs (e.g., RESTful weather services).

### Key Components
* **Tool Binding & Schema:** External Python functions (like `get_live_weather`) are mapped to the LLM using `.bind_tools()`. This translates the Python function into a JSON schema, teaching the AI the exact parameters required (e.g., `latitude`, `longitude`).
* **The Alignment Wall (System Prompting):** Foundation models are heavily trained to refuse requests for real-time data. To successfully execute external APIs, the Agent's `SystemMessage` is engineered with highly assertive, explicitly permissive instructions (e.g., "DO NOT REFUSE. You have a tool for this."). This psychological override forces the AI to check its bound tools rather than falling back on canned refusal messages.
* **The Execution Loop:** Once the API returns a JSON payload, the State Machine routes the raw data back to the Agent. The Agent reads the data, synthesizes it, and generates a formatted, human-readable response.
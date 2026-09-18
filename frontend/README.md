# Echo - Frontend

This is the frontend application for the **Echo** project, built with [Next.js](https://nextjs.org/) (React) and TailwindCSS. It utilizes `shadcn/ui` for accessible component primitives, `lucide-react` for iconography, and `zustand` for lightweight state management. It provides the user interface for secure voice interactions and streams audio to the backend.

## Workspace Architecture

This project is located in the `frontend/` directory and operates as a package within the root `pnpm` monorepo workspace. 

### Directory Structure

```text
frontend/
├── app/
│   ├── globals.css                 # Global CSS and Tailwind directives
│   ├── layout.tsx                  # Root Next.js layout
│   ├── page.tsx                    # Main landing page
│   └── spike/                      # Audio streaming integration testing
│       └── page.tsx                # WebSocket + Web Audio API spike page
├── components/
│   └── ui/                         # shadcn/ui shared components
├── lib/
│   └── utils.ts                    # Utility functions (Tailwind merge, clsx)
├── public/                         # Static assets
├── next.config.ts                  # Next.js configuration (Standalone mode)
└── package.json                    # Frontend dependencies
``` 

## Installation & Running

To run the frontend, you should execute commands from the **root** directory of the repository.

1. **Install Dependencies:**
   From the root directory (where the `pnpm-workspace.yaml` is located), run:
   ```bash
   pnpm install
   ```

2. **Start the Development Server:**
   Launch the frontend development server using the root script:
   ```bash
   pnpm run dev:frontend
   ```
   Open your browser and navigate to [http://localhost:3000](http://localhost:3000) to view the application.

3. **Build for Production:**
   To build the optimized Next.js standalone output for production deployment:
   ```bash
   pnpm run build:frontend
   ```

## Audio Streaming Spike

Currently, this project includes an experimental page (spike) designed to test microphone audio capturing and streaming to the backend. 

- **Testing URL:** [http://localhost:3000/spike](http://localhost:3000/spike)

### Proposed Architecture:
1. The Scaffolding UI provides a `Start Recording` and `Stop Recording` functionality.
2. Upon starting, the Frontend uses the `Web Audio API` (e.g., `MediaRecorder`) to capture the user's microphone input.
3. Audio chunks are streamed over a `WebSocket` connection to the FastAPI Backend.
4. The Backend securely processes the stream and communicates with the **Gemini Live API**.

*(Note: The actual implementation logic for the Web Audio API and WebSocket streaming is currently in the scaffolding phase and will be detailed in subsequent updates).*

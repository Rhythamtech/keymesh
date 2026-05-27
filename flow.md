flowchart TD

    %% ====================================
    %% USER APPLICATION
    %% ====================================

    A[User Python Application]

    A --> B[Key Provider SDK]

    %% ====================================
    %% TRANSPORT-LAYER API CREDENTIAL SCHEDULER
    %% ====================================

    subgraph TPS[Transport-layer API Credential Scheduler]

        direction TB

        %% ----------------------------
        %% REQUEST INPUT
        %% ----------------------------

        B --> C[Request Interceptor]

        C --> D[Credential Scheduler]

        %% ----------------------------
        %% API KEY POOL
        %% ----------------------------

        subgraph KP[API Key Pool]

            direction TB

            K1[API Key #1]
            K2[API Key #2]
            K3[API Key #3]
            KN[API Key #N]

        end

        D --> KP

        %% ----------------------------
        %% KEY STATE MANAGER
        %% ----------------------------

        subgraph KSM[Key State Manager]

            direction TB

            S1[Request Counter]
            S2[Rate Limit Tracker]
            S3[Cooldown Tracker]
            S4[Availability Status]
            S5[Concurrency Control]

        end

        D --> KSM

        %% ----------------------------
        %% SCHEDULER LOGIC
        %% ----------------------------

        subgraph SL[Scheduling Logic]

            direction TB

            L1[Round Robin]
            L2[Least Busy Key]
            L3[Weighted Selection]
            L4[Adaptive Selection]

        end

        D --> SL

        %% ----------------------------
        %% KEY SELECTION
        %% ----------------------------

        D --> E[Select Best Available Key]

        %% ----------------------------
        %% HEADER INJECTION
        %% ----------------------------

        E --> F[Inject API Key Into Headers]

        %% ----------------------------
        %% DIRECT REQUEST
        %% ----------------------------

        F --> G[Direct HTTP Request]

    end

    %% ====================================
    %% LLM PROVIDER
    %% ====================================

    G --> H[OpenAI-Compatible Provider]

    %% ====================================
    %% RESPONSE FLOW
    %% ====================================

    H --> I[Provider Response]

    %% ====================================
    %% RESPONSE ANALYZER
    %% ====================================

    I --> J{Response Status}

    %% ----------------------------
    %% SUCCESS
    %% ----------------------------

    J -->|200 OK| K[Update Success Metrics]

    K --> L[Return Response]

    %% ----------------------------
    %% RATE LIMIT
    %% ----------------------------

    J -->|429 Rate Limited| M[Mark Key As Cooling Down]

    M --> N[Remove Key Temporarily]

    N --> D

    %% ----------------------------
    %% PROVIDER FAILURE
    %% ----------------------------

    J -->|5xx Error| O[Increment Failure Score]

    O --> D

    %% ----------------------------
    %% NETWORK FAILURE
    %% ----------------------------

    J -->|Timeout / Connection Error| P[Retry With Another Key]

    P --> D

    %% ====================================
    %% OPTIONAL STORAGE
    %% ====================================

    subgraph STORAGE[Optional Persistent State]

        direction TB

        ST1[(SQLite)]
        ST2[(Redis)]
        ST3[(Local JSON Cache)]

    end

    KSM --> STORAGE


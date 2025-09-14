#!/bin/bash

# Blockchain File Integrity System - Complete Startup Script
# This script starts a full 4-node PBFT network with file monitoring

set -e  # Exit on any error

echo "🚀 Starting Blockchain File Integrity Monitoring System"
echo "============================================================"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check dependencies
echo -e "${BLUE}📋 Checking dependencies...${NC}"

if ! command -v python &> /dev/null; then
    echo -e "${RED}❌ Python  is required but not installed${NC}"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js is required but not installed${NC}"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ npm is required but not installed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All dependencies found${NC}"

# Create directory structure
echo -e "${BLUE}📁 Creating directory structure...${NC}"
mkdir -p data/node{0,1,2,3}
mkdir -p watched/node{0,1,2,3}
mkdir -p logs

# Create sample files for testing
for i in {0..3}; do
    echo "Sample file for node $i - $(date)" > "watched/node${i}/sample_${i}.txt"
    echo "Test document ${i}" > "watched/node${i}/test_doc_${i}.txt"
done

# Install Python dependencies
echo -e "${BLUE}📦 Installing Python dependencies...${NC}"
if [ ! -f "requirements.txt" ]; then
    cat > requirements.txt << EOF
fastapi==0.104.1
uvicorn[standard]==0.24.0
websockets==11.0.3
sqlalchemy==2.0.23
aiofiles==23.2.1
python-multipart==0.0.6
EOF
fi

pip3 install -r requirements.txt

# Install frontend dependencies
echo -e "${BLUE}📦 Installing frontend dependencies...${NC}"
if [ -d "frontend" ]; then
    cd frontend && npm install && cd ..
elif [ -f "package.json" ]; then
    npm install
fi

# Array to store process PIDs
declare -a NODE_PIDS=()
declare -a AGENT_PIDS=()

# Function to start a single node
start_node() {
    local node_id=$1
    local port=$((7000 + node_id))
    local peers=""

    # Build peers list (exclude current node)
    for i in {0..3}; do
        if [ $i -ne $node_id ]; then
            if [ -n "$peers" ]; then
                peers="$peers,http://localhost:$((7000 + i))"
            else
                peers="http://localhost:$((7000 + i))"
            fi
        fi
    done

    echo -e "${BLUE}🔧 Starting Node $node_id on port $port...${NC}"

    # Set environment variables and start node
    export NODE_ID=$node_id
    export PORT=$port
    export TOTAL_NODES=4
    export PEERS=$peers
    export SFIM_DB="sqlite:///./data/node${node_id}/sfim.db"
    export USE_SIMULATED_TPM=true
    export WATCH_PATHS="./watched/node${node_id}"
    export SCAN_INTERVAL=10

    # Start the node in background
    python3 node.py > logs/node${node_id}.log 2>&1 &
    local node_pid=$!
    NODE_PIDS[$node_id]=$node_pid

    echo -e "${GREEN}✅ Node $node_id started (PID: $node_pid)${NC}"

    # Store PID for cleanup
    echo $node_pid > "data/node${node_id}/node.pid"

    # Wait for node to start
    sleep 3
}

# Function to start file agent for a node
start_agent() {
    local node_id=$1
    local port=$((7000 + node_id))

    echo -e "${BLUE}🔍 Starting File Agent for Node $node_id...${NC}"

    export NODE_WS_URL="ws://localhost:${port}/ws"
    export WATCH_PATHS="./watched/node${node_id}"
    export SCAN_INTERVAL=10
    export SFIM_DB="sqlite:///./data/node${node_id}/agent_sfim.db"

    python3 agent.py > logs/agent${node_id}.log 2>&1 &
    local agent_pid=$!
    AGENT_PIDS[$node_id]=$agent_pid

    echo -e "${GREEN}✅ Agent $node_id started (PID: $agent_pid)${NC}"

    echo $agent_pid > "data/node${node_id}/agent.pid"
}

# Function to cleanup all processes
cleanup() {
    echo -e "${YELLOW}🛑 Shutting down all processes...${NC}"

    # Kill all node processes
    for i in {0..3}; do
        if [ -f "data/node${i}/node.pid" ]; then
            local pid=$(cat "data/node${i}/node.pid")
            kill $pid 2>/dev/null || true
            rm -f "data/node${i}/node.pid"
        fi

        if [ -f "data/node${i}/agent.pid" ]; then
            local pid=$(cat "data/node${i}/agent.pid")
            kill $pid 2>/dev/null || true
            rm -f "data/node${i}/agent.pid"
        fi
    done

    # Kill frontend
    if [ -f "frontend.pid" ]; then
        kill $(cat frontend.pid) 2>/dev/null || true
        rm -f frontend.pid
    fi

    # Kill any remaining processes
    pkill -f "python3 node.py" 2>/dev/null || true
    pkill -f "python3 agent.py" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null || true

    echo -e "${GREEN}✅ All processes stopped${NC}"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM EXIT

# Initialize databases
echo -e "${BLUE}🗄️ Initializing databases...${NC}"
for i in {0..3}; do
    export SFIM_DB="sqlite:///./data/node${i}/sfim.db"
    python3 db_init.py --seed
done

# Start all nodes
echo -e "${BLUE}🌐 Starting PBFT network (4 nodes)...${NC}"
for i in {0..3}; do
    start_node $i
done

# Wait for nodes to establish connections
echo -e "${YELLOW}⏳ Waiting for nodes to establish peer connections...${NC}"
sleep 15

# Verify nodes are running
echo -e "${BLUE}🔍 Verifying node status...${NC}"
for i in {0..3}; do
    if curl -s "http://localhost:$((7000 + i))/api/status" > /dev/null; then
        echo -e "${GREEN}✅ Node $i is responding${NC}"
    else
        echo -e "${RED}❌ Node $i is not responding${NC}"
    fi
done

# Start file agents
echo -e "${BLUE}🔍 Starting file monitoring agents...${NC}"
for i in {0..3}; do
    start_agent $i
done

# Wait for agents to connect
sleep 5

# Start frontend
echo -e "${BLUE}🖥️ Starting frontend...${NC}"
if [ -d "frontend" ]; then
    cd frontend
    export NEXT_PUBLIC_API_URL=http://localhost:7000
    npm run dev > ../logs/frontend.log 2>&1 &
    cd ..
elif [ -f "package.json" ]; then
    export NEXT_PUBLIC_API_URL=http://localhost:7000
    npm run dev > logs/frontend.log 2>&1 &
fi

frontend_pid=$!
echo $frontend_pid > frontend.pid
echo -e "${GREEN}✅ Frontend started (PID: $frontend_pid)${NC}"

# Wait for frontend to start
sleep 5

# Test the system
echo -e "${BLUE}🧪 Running system tests...${NC}"

# Test node connectivity
for i in {0..3}; do
    if curl -s "http://localhost:$((7000 + i))/api/status" | grep -q "node_id"; then
        echo -e "${GREEN}✅ Node $i API is working${NC}"
    else
        echo -e "${YELLOW}⚠️ Node $i API may not be fully ready${NC}"
    fi
done

# Display comprehensive status
echo ""
echo -e "${GREEN}🎉 Blockchain File Integrity System is now running!${NC}"
echo "============================================================"
echo -e "${BLUE}📊 System Status:${NC}"
echo "  • Node 0 (Primary):  http://localhost:7000"
echo "  • Node 1:            http://localhost:7001"
echo "  • Node 2:            http://localhost:7002"
echo "  • Node 3:            http://localhost:7003"
echo "  • Frontend:          http://localhost:3000"
echo ""
echo -e "${BLUE}📁 Watch Directories:${NC}"
for i in {0..3}; do
    echo "  • Node $i: ./watched/node${i}/"
done
echo ""
echo -e "${BLUE}📋 API Endpoints (Node 0):${NC}"
echo "  • Upload File:       POST http://localhost:7000/api/upload"
echo "  • Verify File:       POST http://localhost:7000/api/verify"
echo "  • List Files:        GET  http://localhost:7000/api/files"
echo "  • System Status:     GET  http://localhost:7000/api/status"
echo "  • Events:            GET  http://localhost:7000/api/events"
echo "  • TPM Quotes:        GET  http://localhost:7000/api/quotes"
echo "  • WebSocket:         ws://localhost:7000/ws"
echo ""
echo -e "${BLUE}📄 Log Files:${NC}"
echo "  • Node logs:         ./logs/node{0,1,2,3}.log"
echo "  • Agent logs:        ./logs/agent{0,1,2,3}.log"
echo "  • Frontend log:      ./logs/frontend.log"
echo ""
echo -e "${BLUE}🧪 Testing Guide:${NC}"
echo "  1. Open frontend at http://localhost:3000"
echo "  2. Upload a file through the web interface"
echo "  3. Watch consensus process in logs: tail -f logs/node0.log"
echo "  4. Add files to ./watched/node0/ to trigger monitoring"
echo "  5. Check file integrity: curl -X GET http://localhost:7000/api/files"
echo ""
echo -e "${BLUE}🔍 Monitoring Commands:${NC}"
echo "  • Watch Node 0 logs:     tail -f logs/node0.log"
echo "  • Watch Agent logs:      tail -f logs/agent0.log"
echo "  • Check node status:     curl http://localhost:7000/api/status"
echo "  • View all events:       curl http://localhost:7000/api/events"
echo "  • Monitor file changes:  watch -n 5 'ls -la watched/node0/'"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo "============================================================"

# Function to show running processes
show_processes() {
    echo -e "${BLUE}📋 Running Processes:${NC}"
    for i in {0..3}; do
        if [ -f "data/node${i}/node.pid" ] && kill -0 $(cat "data/node${i}/node.pid") 2>/dev/null; then
            echo -e "${GREEN}✅ Node $i is running (PID: $(cat "data/node${i}/node.pid"))${NC}"
        else
            echo -e "${RED}❌ Node $i is not running${NC}"
        fi

        if [ -f "data/node${i}/agent.pid" ] && kill -0 $(cat "data/node${i}/agent.pid") 2>/dev/null; then
            echo -e "${GREEN}✅ Agent $i is running (PID: $(cat "data/node${i}/agent.pid"))${NC}"
        else
            echo -e "${RED}❌ Agent $i is not running${NC}"
        fi
    done

    if [ -f "frontend.pid" ] && kill -0 $(cat frontend.pid) 2>/dev/null; then
        echo -e "${GREEN}✅ Frontend is running (PID: $(cat frontend.pid))${NC}"
    else
        echo -e "${RED}❌ Frontend is not running${NC}"
    fi
}

# Periodic status check
while true; do
    sleep 30

    # Check if any process died
    for i in {0..3}; do
        if [ -f "data/node${i}/node.pid" ] && ! kill -0 $(cat "data/node${i}/node.pid") 2>/dev/null; then
            echo -e "${RED}⚠️ Node $i has stopped! Check logs/node${i}.log${NC}"
        fi

        if [ -f "data/node${i}/agent.pid" ] && ! kill -0 $(cat "data/node${i}/agent.pid") 2>/dev/null; then
            echo -e "${RED}⚠️ Agent $i has stopped! Check logs/agent${i}.log${NC}"
        fi
    done

    if [ -f "frontend.pid" ] && ! kill -0 $(cat frontend.pid) 2>/dev/null; then
        echo -e "${RED}⚠️ Frontend has stopped! Check logs/frontend.log${NC}"
    fi
done
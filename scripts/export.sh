#!/bin/bash
# Nexus System Export Script
# Exports methodology core (shareable) while stripping personal data
# Usage: ./export.sh [output_dir]

set -e

OUTPUT_DIR="${1:-./export-$(date +%Y%m%d)}"
NEXUS_DIR="$HOME/.claude/nexus"
SKILLS_DIR="$HOME/.claude/skills"
CLAUDE_GLOBAL="$HOME/.claude/CLAUDE.md"
CLAUDE_PROJECT="$HOME/claude-projects/CLAUDE.md"

echo "=== Nexus Package Export ==="
echo "Output: $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"/{architecture,protocols,quality,schemas,skills,methodology,output-spec}

# --- 1. Architecture Core ---
echo "[1/7] Exporting architecture..."
cp "$NEXUS_DIR/architecture.yaml" "$OUTPUT_DIR/architecture/"

# --- 2. Protocols (all shareable) ---
echo "[2/7] Exporting protocols..."
cp "$NEXUS_DIR/protocols/"*.md "$OUTPUT_DIR/protocols/"

# --- 3. Quality System (rules + scripts, NOT data) ---
echo "[3/7] Exporting quality system..."
cp "$NEXUS_DIR/quality/rules.yaml" "$OUTPUT_DIR/quality/" 2>/dev/null || true
cp "$NEXUS_DIR/quality/enforcement-triggers.yaml" "$OUTPUT_DIR/quality/" 2>/dev/null || true
cp "$NEXUS_DIR/quality/enforcement-registry.json" "$OUTPUT_DIR/quality/" 2>/dev/null || true
cp "$NEXUS_DIR/quality/validate.sh" "$OUTPUT_DIR/quality/" 2>/dev/null || true
cp "$NEXUS_DIR/quality/scorecard-script.py" "$OUTPUT_DIR/quality/" 2>/dev/null || true
cp "$NEXUS_DIR/quality/action-triggers.json" "$OUTPUT_DIR/quality/" 2>/dev/null || true

# --- 4. Schemas (data contracts) ---
echo "[4/7] Exporting schemas..."
find "$NEXUS_DIR" -name "_schema.json" -exec cp {} "$OUTPUT_DIR/schemas/" \;
cp "$NEXUS_DIR/tasks/lifecycle.json" "$OUTPUT_DIR/schemas/" 2>/dev/null || true
cp "$NEXUS_DIR/tasks/templates.json" "$OUTPUT_DIR/schemas/" 2>/dev/null || true
cp "$NEXUS_DIR/signals/routing.json" "$OUTPUT_DIR/schemas/" 2>/dev/null || true

# --- 5. Skills (all generic, no personal data) ---
echo "[5/7] Exporting skills..."
EXPORT_SKILLS=(
    "earnings-workflow"
    "comps-analysis"
    "dcf-model"
    "thesis-memo"
    "xlsx"
    "yahoo-finance"
    "deep-research"
    "market-pulse"
    "data-visualization"
    "web-access"
    "verification-before-completion"
    "agent-orchestrator"
    "ohim-research-standards"
    "akshare-china"
    "systematic-debugging"
)
for skill in "${EXPORT_SKILLS[@]}"; do
    if [ -d "$SKILLS_DIR/$skill" ]; then
        cp -r "$SKILLS_DIR/$skill" "$OUTPUT_DIR/skills/"
    fi
done

# --- 6. Methodology (CLAUDE.md, stripped of personal sections) ---
echo "[6/7] Exporting methodology..."

# Global CLAUDE.md: keep everything EXCEPT personal sections
sed -E '/^## 认知校准：你在跟一个怎样的人合作/,/^---$/{
    s/Buwen Deng，东方港湾股票研究员，PKU\+NUS背景/[USER]，[FIRM]研究员/
    s/Buwen/[USER]/g
}' "$CLAUDE_GLOBAL" | \
sed '/^<!-- MODEL_POLICY_START/,/^<!-- MODEL_POLICY_END/d' \
> "$OUTPUT_DIR/methodology/CLAUDE_global.md"

# Project CLAUDE.md: keep research methodology + operational triggers
cp "$CLAUDE_PROJECT" "$OUTPUT_DIR/methodology/CLAUDE_project.md"

# --- 7. Output Spec ---
echo "[7/7] Copying output spec..."
if [ -d "$(dirname "$0")/../output-spec" ]; then
    cp "$(dirname "$0")/../output-spec/"* "$OUTPUT_DIR/output-spec/" 2>/dev/null || true
fi

# --- Summary ---
echo ""
echo "=== Export Complete ==="
FILE_COUNT=$(find "$OUTPUT_DIR" -type f | wc -l | tr -d ' ')
TOTAL_SIZE=$(du -sh "$OUTPUT_DIR" | cut -f1)
echo "Files: $FILE_COUNT"
echo "Size: $TOTAL_SIZE"
echo "Location: $OUTPUT_DIR"
echo ""
echo "=== VERIFICATION CHECKLIST ==="
echo "[ ] No personal positions/tickers in output"
echo "[ ] No credentials/account info"
echo "[ ] No career/job search data"
echo "[ ] No specific price targets or thesis opinions"
echo "[ ] CLAUDE.md user references anonymized"
echo ""
echo "Run: grep -r 'portfolio_state\|buwen\|OHIM\|东方港湾' $OUTPUT_DIR"
echo "^ Should return 0 results (or only methodology references, not data)"

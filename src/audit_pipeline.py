"""
audit_pipeline.py
=================
CLI for the M1 vertical slice: ingests a contract, dispatches it to a domain
agent, and outputs the structured audit flags and trace.
"""

import argparse
import json
import os
from pathlib import Path

from src.contract_loader import load_contract
from src.agents.base_agent import DomainAgent
from src.llm_client import settings


def main():
    parser = argparse.ArgumentParser(description="Audit a contract against a legal domain.")
    parser.add_argument("contract_path", type=str, help="Path to the contract file (PDF, DOCX, TXT)")
    parser.add_argument("--domain", type=str, default="civil", help="Legal domain (e.g. civil, commercial)")
    parser.add_argument("--out", type=str, default="outputs/audit_report.json", help="Path to save the JSON report")
    
    args = parser.parse_args()

    contract_path = Path(args.contract_path)
    if not contract_path.exists():
        print(f"Error: Contract file not found at {contract_path}")
        return

    # 1. Ingest Contract
    print(f"Loading contract from {contract_path}...")
    doc = load_contract(contract_path)
    print(f"Loaded {len(doc.text)} characters, split into {len(doc.clauses)} clauses.")

    # 2. Setup Agent
    index_path = Path(f"data/index/{args.domain}")
    playbook_path = Path(f"playbooks/{args.domain}.yaml")
    
    if not index_path.exists():
        print(f"Error: Index for domain '{args.domain}' not found at {index_path}.")
        return
    if not playbook_path.exists():
        print(f"Error: Playbook for domain '{args.domain}' not found at {playbook_path}.")
        return

    agent = DomainAgent(
        name=args.domain,
        index_path=index_path,
        playbook_path=playbook_path
    )

    # 3. Run Audit
    print(f"\nStarting autonomous audit agent for {args.domain.title()} Law...")
    print(f"Using LLM: {settings.llm_model}")
    print("-" * 50)
    
    result = agent.run(doc.text)
    
    # 4. Process and Save Output
    flags = result.get("flags", [])
    trace = result.get("trace", [])
    summary = result.get("summary", "")
    
    print("\n" + "=" * 50)
    print("AUDIT COMPLETE")
    print("=" * 50)
    print(f"Agent Summary:\n{summary}\n")
    
    print(f"Identified {len(flags)} Risks:")
    for flag in flags:
        severity = flag.get('severity', 'UNKNOWN')
        print(f"\n[{severity}] {flag.get('check_id', 'Uncategorized')}")
        print(f"Rationale: {flag.get('rationale')}")
        print(f"Evidence: \"{flag.get('evidence_span')}\"")
        print(f"Article Ref: {flag.get('article_ref')}")
        
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    print(f"\nDetailed report and tool-call trace saved to {out_path}")

if __name__ == "__main__":
    main()

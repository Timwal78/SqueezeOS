import os
import requests
import json
import logging
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("SalesAgent")

class SqueezeOSSalesAgent:
    """
    An automated outreach agent that uses an LLM to generate highly personalized 
    sales pitches for the SqueezeOS API.
    """
    def __init__(self):
        # We can use the existing SqueezeOS LLM setup or Claude directly
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.pricing_url = "https://squeezeos-api.onrender.com/pricing"
        self.github_url = "https://github.com/Timwal78/SqueezeOS"

    def _generate_pitch(self, developer_profile: Dict) -> str:
        """Uses Claude to generate a tailored outreach message."""
        if not self.api_key:
            return f"Hey {developer_profile.get('name', 'there')}, check out SqueezeOS API for institutional options flow! {self.pricing_url}"

        prompt = f"""
        You are an elite institutional sales agent for SqueezeOS. 
        SqueezeOS is a premium algorithmic trading API that provides Base-4 Fractal Convergence scans and Gamma/Options Flow analysis.
        
        Write a concise, high-converting, 3-sentence DM to this developer:
        Name: {developer_profile.get('name')}
        Bio/Repo Focus: {developer_profile.get('bio')}
        
        Make it sound like one quant talking to another. No marketing fluff. 
        End with a call to action pointing to {self.pricing_url}
        """

        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 150,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            return data.get("content", [{}])[0].get("text", "Error generating pitch.")
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return "Failed to generate AI pitch."

    def find_leads(self, keyword: str = "algorithmic trading python", limit: int = 5) -> List[Dict]:
        """Scrapes GitHub for developers working on specific algo-trading keywords."""
        logger.info(f"🔍 Searching GitHub for leads using keyword: '{keyword}'...")
        
        # Simple GitHub search API (no auth needed for low volume)
        url = f"https://api.github.com/search/repositories?q={keyword}&sort=stars&order=desc&per_page={limit}"
        response = requests.get(url)
        
        leads = []
        if response.status_code == 200:
            repos = response.json().get('items', [])
            for repo in repos:
                owner = repo.get('owner', {})
                leads.append({
                    "name": owner.get('login'),
                    "repo": repo.get('name'),
                    "bio": repo.get('description'),
                    "url": owner.get('html_url')
                })
        return leads

    def run_campaign(self):
        print("="*50)
        print("🤖 SQUEEZE-OS SALES AGENT INITIALIZED")
        print("="*50)
        
        leads = self.find_leads("options flow algorithmic trading", limit=3)
        if not leads:
            print("No leads found.")
            return

        for lead in leads:
            print(f"\n[LEAD IDENTIFIED]: {lead['name']} ({lead['repo']})")
            print(f"Generating personalized pitch...")
            
            pitch = self._generate_pitch(lead)
            
            print("-" * 40)
            print(f"TO: {lead['url']}")
            print(f"MESSAGE:\n{pitch}")
            print("-" * 40)
            print("Action: Copy this and send via Twitter/GitHub/Email.")

if __name__ == "__main__":
    agent = SqueezeOSSalesAgent()
    agent.run_campaign()

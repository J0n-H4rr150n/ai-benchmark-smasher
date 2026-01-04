import re
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse


class WebAnalyzer:
    """Analyzes web pages for CTF patterns and vulnerabilities"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(follow_redirects=True, timeout=30.0)
    
    async def analyze_url(self, url: str) -> Dict[str, Any]:
        """Perform comprehensive analysis of a URL"""
        findings = {
            "url": url,
            "flags": [],
            "vulnerabilities": [],
            "interesting_findings": [],
            "forms": [],
            "links": [],
            "scripts": [],
            "comments": []
        }
        
        try:
            # Fetch the page
            response = await self.http_client.get(url)
            findings["status_code"] = response.status_code
            findings["headers"] = dict(response.headers)
            
            # Parse content
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find FLAGS
            findings["flags"] = self.find_flags(response.text)
            
            # Analyze forms
            findings["forms"] = self.analyze_forms(soup, url)
            
            # Find hidden fields
            findings["interesting_findings"].extend(self.find_hidden_fields(soup))
            
            # Extract links
            findings["links"] = self.extract_links(soup, url)
            
            # Find JavaScript
            findings["scripts"] = self.extract_scripts(soup)
            
            # Extract HTML comments
            findings["comments"] = self.extract_comments(soup)
            
            # Check for common vulnerabilities
            findings["vulnerabilities"] = self.check_vulnerabilities(soup, response.text)
            
        except Exception as e:
            findings["error"] = str(e)
        
        return findings
    
    def find_flags(self, content: str) -> List[str]:
        """Find FLAG{} patterns in content"""
        pattern = r'FLAG\{[^}]+\}'
        return re.findall(pattern, content, re.IGNORECASE)
    
    def analyze_forms(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
        """Analyze all forms on the page"""
        forms = []
        for form in soup.find_all('form'):
            form_data = {
                "action": urljoin(base_url, form.get('action', '')),
                "method": form.get('method', 'get').upper(),
                "inputs": []
            }
            
            for input_tag in form.find_all(['input', 'textarea', 'select']):
                form_data["inputs"].append({
                    "type": input_tag.get('type', 'text'),
                    "name": input_tag.get('name'),
                    "value": input_tag.get('value'),
                    "required": input_tag.has_attr('required')
                })
            
            forms.append(form_data)
        
        return forms
    
    def find_hidden_fields(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Find hidden input fields"""
        hidden_fields = []
        for hidden in soup.find_all('input', type='hidden'):
            hidden_fields.append({
                "finding_type": "hidden_field",
                "name": hidden.get('name'),
                "value": hidden.get('value'),
                "description": f"Hidden field: {hidden.get('name')} = {hidden.get('value')}"
            })
        return hidden_fields
    
    def extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all links from the page"""
        links = []
        for link in soup.find_all('a', href=True):
            absolute_url = urljoin(base_url, link['href'])
            links.append(absolute_url)
        return list(set(links))
    
    def extract_scripts(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract JavaScript from the page"""
        scripts = []
        for script in soup.find_all('script'):
            if script.string:
                scripts.append({
                    "type": "inline",
                    "content": script.string
                })
            elif script.get('src'):
                scripts.append({
                    "type": "external",
                    "src": script.get('src')
                })
        return scripts
    
    def extract_comments(self, soup: BeautifulSoup) -> List[str]:
        """Extract HTML comments"""
        from bs4 import Comment
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        return [str(comment).strip() for comment in comments]
    
    def check_vulnerabilities(self, soup: BeautifulSoup, content: str) -> List[Dict[str, str]]:
        """Check for common CTF vulnerability patterns"""
        vulns = []
        
        # Check for potential SQL injection points
        for form in soup.find_all('form'):
            for input_field in form.find_all('input'):
                if input_field.get('type') in ['text', 'search', None]:
                    vulns.append({
                        "type": "potential_sql_injection",
                        "description": f"Text input field: {input_field.get('name')} might be vulnerable",
                        "location": f"Form action: {form.get('action')}"
                    })
        
        # Check for base64 encoded data
        base64_pattern = r'[A-Za-z0-9+/]{20,}={0,2}'
        base64_matches = re.findall(base64_pattern, content)
        if base64_matches:
            vulns.append({
                "type": "base64_encoded_data",
                "description": f"Found {len(base64_matches)} potential base64 strings",
                "examples": base64_matches
            })
        
        return vulns
    
    async def close(self):
        """Close the HTTP client"""
        await self.http_client.aclose()

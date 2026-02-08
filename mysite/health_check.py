#!/usr/bin/env python3
"""
UN Treaty Body Database - System Health Check Script
Run this to verify all components are working correctly
"""

import os
import sys
import json
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_status(status, message):
    """Print colored status message"""
    if status == "OK":
        print(f"{GREEN}✓{RESET} {message}")
    elif status == "ERROR":
        print(f"{RED}✗{RESET} {message}")
    elif status == "WARNING":
        print(f"{YELLOW}⚠{RESET} {message}")
    else:
        print(f"{BLUE}ℹ{RESET} {message}")

def check_file(filepath, description):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print_status("OK", f"{description}: {filepath}")
        return True
    else:
        print_status("ERROR", f"{description} NOT FOUND: {filepath}")
        return False

def check_directory(dirpath, description, check_writable=False):
    """Check if a directory exists and optionally if it's writable"""
    if os.path.exists(dirpath):
        if check_writable:
            test_file = os.path.join(dirpath, '.write_test')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                print_status("OK", f"{description}: {dirpath} (writable)")
                return True
            except:
                print_status("ERROR", f"{description}: {dirpath} (NOT writable)")
                return False
        else:
            print_status("OK", f"{description}: {dirpath}")
            return True
    else:
        print_status("ERROR", f"{description} NOT FOUND: {dirpath}")
        return False

def check_python_module(module_name):
    """Check if a Python module is installed"""
    try:
        __import__(module_name)
        print_status("OK", f"Module {module_name} is installed")
        return True
    except ImportError:
        print_status("ERROR", f"Module {module_name} is NOT installed")
        return False

def main():
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}UN Treaty Body Database - System Health Check{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    base_dir = "/home/lszoszk/mysite"
    errors = 0
    warnings = 0
    
    # Check Python version
    print(f"{BLUE}Python Environment:{RESET}")
    python_version = sys.version_info
    if python_version.major == 3 and python_version.minor >= 8:
        print_status("OK", f"Python {python_version.major}.{python_version.minor}.{python_version.micro}")
    else:
        print_status("WARNING", f"Python {python_version.major}.{python_version.minor}.{python_version.micro} (recommend 3.8+)")
        warnings += 1
    print()
    
    # Check critical files
    print(f"{BLUE}Critical Files:{RESET}")
    critical_files = [
        (f"{base_dir}/app.py", "Main application"),
        (f"{base_dir}/crc_gc_info.json", "CRC metadata"),
        (f"{base_dir}/specialprocedures_info.json", "SP metadata"),
    ]
    
    for filepath, description in critical_files:
        if not check_file(filepath, description):
            errors += 1
    print()
    
    # Check template files
    print(f"{BLUE}Template Files:{RESET}")
    templates_dir = f"{base_dir}/templates"
    required_templates = [
        "navbar_universal.html",
        "index2.html",
        "404.html",
        "500.html",
        "browse.html",
        "about.html",
        "search_results.html",
    ]
    
    for template in required_templates:
        if not check_file(f"{templates_dir}/{template}", f"Template {template}"):
            errors += 1
    
    # Check optional templates
    optional_templates = [
        "vibecoding.html",
        "sp_documents.html",
        "corpus_viewer.html",
        "contact.html",
        "enhanced_home.html",
        "search_results_enhanced.html",
        "specialprocedures.html",
        "neurorights_search.html",
    ]
    
    print(f"\n{BLUE}Optional Templates:{RESET}")
    for template in optional_templates:
        if not os.path.exists(f"{templates_dir}/{template}"):
            print_status("WARNING", f"Optional template missing: {template}")
            warnings += 1
    print()
    
    # Check directories
    print(f"{BLUE}Required Directories:{RESET}")
    directories = [
        (f"{base_dir}/static", "Static files", False),
        (f"{base_dir}/json_data", "JSON data", False),
        (f"{base_dir}/logs", "Log files", True),
        (f"{base_dir}/cache", "Cache files", True),
        (f"{base_dir}/flask_session", "Session files", True),
    ]
    
    for dirpath, description, check_write in directories:
        if not check_directory(dirpath, description, check_write):
            errors += 1
    print()
    
    # Check Python modules
    print(f"{BLUE}Python Modules:{RESET}")
    required_modules = [
        "flask",
        "flask_session",
        "flask_caching",
        "pandas",
        "nltk",
        "bs4",
        "markupsafe",
        "werkzeug",
    ]
    
    for module in required_modules:
        if not check_python_module(module):
            errors += 1
    
    # Check optional modules
    optional_modules = [
        "bleach",
        "flask_limiter",
        "dotenv",
        "redis",
    ]
    
    print(f"\n{BLUE}Optional Modules (for enhanced security):{RESET}")
    for module in optional_modules:
        if not check_python_module(module):
            warnings += 1
    print()
    
    # Check environment variables
    print(f"{BLUE}Environment Configuration:{RESET}")
    env_file = f"{base_dir}/.env"
    if os.path.exists(env_file):
        print_status("OK", ".env file exists")
        try:
            with open(env_file, 'r') as f:
                env_content = f.read()
                if 'SECRET_KEY=' in env_content:
                    print_status("OK", "SECRET_KEY is configured")
                else:
                    print_status("WARNING", "SECRET_KEY not found in .env")
                    warnings += 1
        except:
            print_status("ERROR", "Cannot read .env file")
            errors += 1
    else:
        print_status("WARNING", ".env file not found (using defaults)")
        warnings += 1
    
    # Check data files
    print(f"\n{BLUE}Data Integrity:{RESET}")
    json_dir = f"{base_dir}/json_data"
    if os.path.exists(json_dir):
        json_files = list(Path(json_dir).glob("*.json"))
        print_status("INFO", f"Found {len(json_files)} JSON data files")
        
        # Test reading a sample file
        if json_files:
            try:
                with open(json_files[0], 'r', encoding='utf-8') as f:
                    json.load(f)
                print_status("OK", "JSON files are readable")
            except Exception as e:
                print_status("ERROR", f"Cannot read JSON files: {e}")
                errors += 1
    else:
        print_status("ERROR", "JSON data directory not found")
        errors += 1
    
    # Summary
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}Summary:{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    if errors == 0 and warnings == 0:
        print(f"{GREEN}✓ All checks passed! The system is ready.{RESET}")
    elif errors == 0:
        print(f"{YELLOW}⚠ System is functional with {warnings} warning(s).{RESET}")
    else:
        print(f"{RED}✗ Found {errors} error(s) and {warnings} warning(s).{RESET}")
        print(f"{RED}Please fix the errors before running the application.{RESET}")
    
    print(f"\n{BLUE}Next Steps:{RESET}")
    if errors > 0:
        print("1. Fix the errors listed above")
        print("2. Run this script again to verify")
        print("3. Restart the application")
    else:
        print("1. Restart your application (reload in PythonAnywhere)")
        print("2. Check the application logs for any runtime errors")
        print("3. Test all main routes in your browser")
    
    return 0 if errors == 0 else 1

if __name__ == "__main__":
    sys.exit(main())

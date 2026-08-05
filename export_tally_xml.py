import sqlite3
import html
import json

conn = sqlite3.connect('data/shopbridge.db')
cur = conn.cursor()
cur.execute('SELECT name, stock_group, unit_name, aliases FROM tally_items WHERE active_status="active"')

xml = []
xml.append("<ENVELOPE>")
xml.append(" <HEADER>")
xml.append("  <TALLYREQUEST>Import Data</TALLYREQUEST>")
xml.append(" </HEADER>")
xml.append(" <BODY>")
xml.append("  <IMPORTDATA>")
xml.append("   <REQUESTDESC>")
xml.append("    <REPORTNAME>All Masters</REPORTNAME>")
xml.append("   </REQUESTDESC>")
xml.append("   <REQUESTDATA>")

for row in cur.fetchall():
    name = row[0] or ""
    stock_group = row[1] or "Primary"
    unit_name = row[2] or "PCS"
    aliases_raw = row[3]
    
    aliases = []
    if aliases_raw:
        if aliases_raw.startswith('[') and aliases_raw.endswith(']'):
            try:
                aliases = json.loads(aliases_raw)
            except:
                aliases = [aliases_raw]
        else:
            aliases = [a.strip() for a in aliases_raw.split(',') if a.strip()]
            
    # Gather all names and split by pipe
    all_names = set()
    
    # Split the main name just in case it has a pipe
    for part in name.split('|'):
        if part.strip():
            all_names.add(part.strip())
            
    # Split all aliases by pipe
    for alias in aliases:
        for part in alias.split('|'):
            if part.strip():
                all_names.add(part.strip())
                
    # Tally needs the first NAME to be the primary item name
    primary_name = name.split('|')[0].strip() if name else ""
    if primary_name in all_names:
        all_names.remove(primary_name)
        
    xml.append('    <TALLYMESSAGE xmlns:UDF="TallyUDF">')
    xml.append(f'     <STOCKITEM NAME="{html.escape(name)}" ACTION="Create">') # ACTION='Create' uses the exact original name for reference
    xml.append('      <NAME.LIST>')
    if primary_name:
        xml.append(f'       <NAME>{html.escape(primary_name)}</NAME>')
    for alias_part in sorted(all_names):
        xml.append(f'       <NAME>{html.escape(alias_part)}</NAME>')
    xml.append('      </NAME.LIST>')
    xml.append(f'      <PARENT>{html.escape(stock_group)}</PARENT>')
    xml.append(f'      <BASEUNITS>{html.escape(unit_name)}</BASEUNITS>')
    xml.append('     </STOCKITEM>')
    xml.append('    </TALLYMESSAGE>')

xml.append("   </REQUESTDATA>")
xml.append("  </IMPORTDATA>")
xml.append(" </BODY>")
xml.append("</ENVELOPE>")

with open("exports/tally_items_import.xml", "w", encoding="utf-8") as f:
    f.write("\n".join(xml))

print("XML Export complete (with pipe splitting)")

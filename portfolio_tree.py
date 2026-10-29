import graphviz


def create_client_portfolio_chart():
  # Initialize directed graph with left-to-right layout
  dot = graphviz.Digraph(comment="Client Investment Portfolio", format="png")
  dot.attr(rankdir="LR", splines="ortho", nodesep="0.4", ranksep="0.7")
  dot.attr(
      "node",
      fontname="Helvetica",
      style="filled",
      fillcolor="white",
      color="#E2E8F0",
      penwidth="1.5",
  )

  # --- Root Node (YOU) ---
  dot.node(
      "YOU",
      """<
  <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="10">
    <TR><TD ALIGN="CENTER"><FONT FACE="Helvetica Bold" POINT-SIZE="14" COLOR="white">&#127968; YOU</FONT></TD></TR>
  </TABLE>
  >""",
      style="filled",
      fillcolor="#1E293B",
      color="#1E293B",
  )

  # --- Entity Categories (Level 1) ---
  categories = {
      "personal": {
          "title": "Personally owned",
          "subtitle": "4 holdings • $1.43M equity",
          "costs": "Costs $263/wk",
          "color": "#3B82F6",
      },
      "super": {
          "title": "Alex Family Super Fund",
          "subtitle": "2 holdings • $310k equity",
          "costs": "Pays $287/wk",
          "color": "#F59E0B",
      },
      "company": {
          "title": "Abc Pty Ltd",
          "subtitle": "1 holding • $450k equity",
          "costs": "Pays $342/wk",
          "color": "#EF4444",
      },
  }

  for cat_id, cat in categories.items():
    dot.node(
        cat_id,
        f"""<
    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="8">
      <TR><TD><FONT FACE="Helvetica Bold" POINT-SIZE="13" COLOR="#0F172A">{cat['title']}</FONT></TD></TR>
      <TR><TD><FONT FACE="Helvetica" POINT-SIZE="10" COLOR="#64748B">{cat['subtitle']}</FONT></TD></TR>
      <TR><TD><FONT FACE="Helvetica Bold" POINT-SIZE="10" COLOR="#DC2626">{cat['costs']}</FONT></TD></TR>
    </TABLE>
    >""",
        shape="box",
        style="rounded,filled",
        fillcolor="white",
        color=cat["color"],
    )
    # Root to category connections (clean lines without arrows)
    dot.edge("YOU", cat_id, color=cat["color"], penwidth="2", arrowhead="none")

  # --- Holdings with Profit & Margin Calculations (Level 2) ---
  holdings = {
      # Personally owned holdings
      "h1": {
          "parent": "personal",
          "name": "Our home, Brisbane",
          "purchase": 850000,
          "current": 1100000,
          "tag_color": "#3B82F6",
      },
      "h2": {
          "parent": "personal",
          "name": "IP1 Brisbane house",
          "purchase": 550000,
          "current": 750000,
          "extra": "Costs $111/wk",
          "tag_color": "#3B82F6",
      },
      "h3": {
          "parent": "personal",
          "name": "IP2 Sunshine Coast unit",
          "purchase": 420000,
          "current": 520000,
          "extra": "Costs $152/wk",
          "tag_color": "#3B82F6",
      },
      "h4": {
          "parent": "personal",
          "name": "Savings",
          "purchase": 107000,
          "current": 107000,
          "tag_color": "#10B981",
      },
      # Super Fund holdings
      "h5": {
          "parent": "super",
          "name": "IP3 Industrial warehouse",
          "purchase": 700000,
          "current": 900000,
          "extra": "Pays $287/wk",
          "tag_color": "#F59E0B",
      },
      "h6": {
          "parent": "super",
          "name": "SMSF cash reserve",
          "purchase": 40000,
          "current": 40000,
          "tag_color": "#F59E0B",
      },
      # Company holdings
      "h7": {
          "parent": "company",
          "name": "Commercial Property",
          "purchase": 1200000,
          "current": 1500000,
          "extra": "Pays $342/wk",
          "tag_color": "#EF4444",
      },
  }

  for h_id, h in holdings.items():
    # Calculate profit and margin dynamically
    profit = h["current"] - h["purchase"]
    margin = (profit / h["purchase"]) * 100 if h["purchase"] > 0 else 0

    # Format currency strings
    curr_str = (
        f"${h['current']/1e6:.1f}M"
        if h["current"] >= 1e6
        else f"${h['current']/1e3:.0f}k"
    )
    purch_str = (
        f"${h['purchase']/1e6:.1f}M"
        if h["purchase"] >= 1e6
        else f"${h['purchase']/1e3:.0f}k"
    )

    if profit >= 0:
      profit_str = f"+${profit/1e3:.0f}k (+{margin:.1f}%)"
      profit_color = "#16A34A"  # Green
    else:
      profit_str = f"-${abs(profit)/1e3:.0f}k ({margin:.1f}%)"
      profit_color = "#DC2626"  # Red

    extra_row = (
        f'<TR><TD><FONT FACE="Helvetica" POINT-SIZE="9" COLOR="#64748B">{h.get("extra", "")}</FONT></TD></TR>'
        if "extra" in h
        else ""
    )

    node_html = f"""<
    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6">
      <TR><TD><FONT FACE="Helvetica Bold" POINT-SIZE="11" COLOR="#0F172A">{h['name']}</FONT></TD></TR>
      <TR><TD><FONT FACE="Helvetica" POINT-SIZE="10" COLOR="#334155">Current: <B>{curr_str}</B> | Bought: {purch_str}</FONT></TD></TR>
      <TR><TD><FONT FACE="Helvetica Bold" POINT-SIZE="10" COLOR="{profit_color}">Profit: {profit_str}</FONT></TD></TR>
      {extra_row}
    </TABLE>
    >"""

    dot.node(
        h_id,
        node_html,
        shape="box",
        style="rounded,filled",
        fillcolor="white",
        color="#CBD5E1",
    )
    # Entity-to-property connections with visible standard arrows (arrowhead="normal")
    dot.edge(
        h["parent"],
        h_id,
        color=h["tag_color"],
        penwidth="2",
        arrowhead="normal",
    )

  # Render output file
  output_file = dot.render("client_portfolio_report_with_arrows", view=True)
  print(f"Portfolio diagram updated with arrows: {output_file}")


if __name__ == "__main__":
  create_client_portfolio_chart()
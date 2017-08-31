<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
  <!--
      use on hocr file to fix for hocr2pdf 0.8.9 textbox placement

      Taken from
      <https://bugs.launchpad.net/cuneiform-linux/+bug/623438/comments/60>.
  -->
  <xsl:template match="/html">
    <xsl:text></xsl:text>
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>
  <xsl:template match="node()|@*">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>
  <xsl:template match="span[@class='ocr_line']">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
    <xsl:element name="br"></xsl:element>
  </xsl:template>
</xsl:stylesheet>

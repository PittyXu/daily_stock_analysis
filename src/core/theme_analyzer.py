# -*- coding: utf-8 -*-
"""
===================================
股票智能分析系统 - 涨停题材分析模块
===================================

职责：
1. 抓取当日涨停池数据
2. 按连板高度构建涨停梯队
3. 搜索归因涨停原因（新闻/公告）
4. 聚类分析题材热点
5. 评分识别题材龙头
6. LLM 判断题材明日延续性
7. 输出潜在龙头标的推荐

使用方式：
    from src.core.theme_analyzer import ThemeAnalyzer
    analyzer = ThemeAnalyzer()
    result = analyzer.analyze(date="20250528")
    print(result.report)      # Markdown 报告
    print(result.recommended) # 推荐标的列表
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LimitUpStock:
    """涨停个股信息"""
    code: str = ""
    name: str = ""
    change_pct: float = 0.0
    price: float = 0.0
    amount: float = 0.0  # 成交额
    turnover_rate: float = 0.0  # 换手率
    seal_amount: float = 0.0  # 封板资金
    first_limit_time: str = ""  # 首次封板时间
    last_limit_time: str = ""  # 最后封板时间
    break_count: int = 0  # 炸板次数
    consecutive_boards: int = 0  # 连板数
    industry: str = ""  # 所属行业


@dataclass
class ThemeCluster:
    """题材聚类结果"""
    theme_name: str  # 题材名称（如"人工智能"、"半导体"）
    stocks: List[LimitUpStock] = field(default_factory=list)
    total_seal_amount: float = 0.0  # 板块封板资金总计
    max_consecutive: int = 0  # 最高连板数
    stock_count: int = 0  # 涨停个股数


@dataclass
class ThemeAnalysisResult:
    """题材分析结果"""
    date: str
    limit_up_pool: List[LimitUpStock] = field(default_factory=list)
    ladder: Dict[int, List[LimitUpStock]] = field(default_factory=dict)  # 连板梯队
    themes: List[ThemeCluster] = field(default_factory=list)
    dragons: List[Dict[str, Any]] = field(default_factory=list)  # 龙头股列表
    llm_continuity: str = ""  # LLM 对题材延续性的判断
    recommended: List[Dict[str, Any]] = field(default_factory=list)  # 推荐标的
    report: str = ""  # Markdown 报告


class ThemeAnalyzer:
    """
    涨停题材分析器
    
    从游资短线交易视角分析当日涨停股，识别题材热点与龙头，
    预判明日延续性并推荐潜在标的。
    """

    def __init__(
        self,
        fetcher=None,
        analyzer=None,
        search_service=None,
    ):
        """
        Args:
            fetcher: 数据获取器（需要 get_limit_up_pool 方法），默认创建 AkshareFetcher
            analyzer: LLM 分析器（GeminiAnalyzer 实例），用于调用 LLM
            search_service: 搜索服务（SearchService 实例），用于新闻检索
        """
        if fetcher is None:
            from data_provider import DataFetcherManager
            self.fetcher = DataFetcherManager()
        else:
            self.fetcher = fetcher

        self.analyzer = analyzer
        self.search_service = search_service

    def analyze(
        self,
        date: Optional[str] = None,
        pool_size: int = 60,
    ) -> ThemeAnalysisResult:
        """
        执行涨停题材分析

        Args:
            date: 日期 YYYYMMDD，默认今天
            pool_size: 涨停池拉取数量（默认60只，足够覆盖当日涨停）

        Returns:
            ThemeAnalysisResult 包含报告、梯队、龙头、推荐标的
        """
        query_date = date or datetime.now().strftime("%Y%m%d")
        result = ThemeAnalysisResult(date=query_date)

        # === 阶段1：拉取涨停池 ===
        logger.info("[ThemeAnalyzer] 阶段1：拉取涨停池 (date=%s, size=%d)...", query_date, pool_size)
        pool_data = self._fetch_limit_up_pool(query_date, pool_size)
        if not pool_data:
            logger.warning("[ThemeAnalyzer] 涨停池为空，跳过题材分析")
            result.report = self._build_empty_report(query_date)
            return result

        result.limit_up_pool = pool_data
        logger.info("[ThemeAnalyzer] 涨停池获取成功，共 %d 只", len(pool_data))

        # === 阶段2：构建涨停梯队 ===
        logger.info("[ThemeAnalyzer] 阶段2：构建涨停梯队...")
        result.ladder = self._build_ladder(pool_data)

        # === 阶段3：题材聚类 ===
        logger.info("[ThemeAnalyzer] 阶段3：题材聚类...")
        result.themes = self._cluster_themes(pool_data)

        # === 阶段4：龙头评分 ===
        logger.info("[ThemeAnalyzer] 阶段4：龙头评分...")
        result.dragons = self._score_dragons(result.themes, result.ladder)

        # === 阶段5：新闻归因（可选，有搜索服务时启用）===
        logger.info("[ThemeAnalyzer] 阶段5：新闻归因...")
        self._enrich_with_news(result)

        # === 阶段6：LLM 延续性判断 ===
        logger.info("[ThemeAnalyzer] 阶段6：LLM 延续性判断...")
        result.llm_continuity = self._llm_continuity_analysis(result)

        # === 阶段7：生成推荐标的 ===
        logger.info("[ThemeAnalyzer] 阶段7：生成推荐标的...")
        result.recommended = self._generate_recommendations(result)

        # === 阶段8：生成报告 ===
        logger.info("[ThemeAnalyzer] 阶段8：生成 Markdown 报告...")
        result.report = self._build_report(result)

        return result

    # ================================================================
    # 阶段1：拉取涨停池
    # ================================================================

    def _fetch_limit_up_pool(
        self, date: str, n: int
    ) -> List[LimitUpStock]:
        """从数据源获取涨停池"""
        try:
            raw = self.fetcher.get_limit_up_pool(date=date, n=n)
            if not raw:
                return []

            stocks = []
            for item in raw:
                stocks.append(LimitUpStock(
                    code=str(item.get("code", "")).strip(),
                    name=str(item.get("name", "")).strip(),
                    change_pct=float(item.get("change_pct") or 0),
                    price=float(item.get("price") or 0),
                    amount=float(item.get("amount") or 0),
                    turnover_rate=float(item.get("turnover_rate") or 0),
                    seal_amount=float(item.get("seal_amount") or 0),
                    first_limit_time=str(item.get("first_limit_time", "")).strip(),
                    last_limit_time=str(item.get("last_limit_time", "")).strip(),
                    break_count=int(item.get("break_count") or 0),
                    consecutive_boards=int(item.get("consecutive_boards") or 0),
                    industry=str(item.get("industry", "")).strip(),
                ))
            return stocks
        except Exception as e:
            logger.warning("[ThemeAnalyzer] 拉取涨停池失败: %s", e)
            return []

    # ================================================================
    # 阶段2：构建涨停梯队
    # ================================================================

    def _build_ladder(
        self, pool: List[LimitUpStock]
    ) -> Dict[int, List[LimitUpStock]]:
        """
        按连板数分组构建涨停梯队
        返回: {连板数: [个股列表]}
        """
        ladder: Dict[int, List[LimitUpStock]] = {}
        for stock in pool:
            board = max(stock.consecutive_boards, 1)
            if board not in ladder:
                ladder[board] = []
            ladder[board].append(stock)

        # 每个梯队内按封板资金排序
        for board in ladder:
            ladder[board].sort(key=lambda s: s.seal_amount, reverse=True)

        return dict(sorted(ladder.items(), reverse=True))

    # ================================================================
    # 阶段3：题材聚类
    # ================================================================

    # 常见题材关键词映射（行业 -> 题材标签）
    _THEME_KEYWORDS = {
        # 科技线
        "半导体": "半导体", "芯片": "半导体", "集成电路": "半导体",
        "电子元件": "电子元件", "光学光电子": "光学光电子",
        "计算机设备": "计算机", "软件开发": "计算机", "IT服务": "计算机",
        "通信设备": "通信", "通信服务": "通信",
        "消费电子": "消费电子",
        # AI / 智能线
        "人工智能": "人工智能", "AI": "人工智能", "大模型": "人工智能",
        "机器人": "机器人", "智能制造": "机器人",
        "无人驾驶": "无人驾驶", "智能驾驶": "无人驾驶", "汽车电子": "无人驾驶",
        "物联网": "物联网", "传感器": "物联网",
        # 新能源线
        "光伏": "光伏", "太阳能": "光伏",
        "锂电池": "锂电", "储能": "储能", "钠离子电池": "钠电池",
        "新能源车": "新能源车", "新能源汽车": "新能源车",
        "氢能源": "氢能源", "燃料电池": "氢能源",
        # 医药线
        "医药": "医药", "化学制药": "医药", "中药": "中药",
        "生物制品": "生物医药", "医疗器械": "医疗器械",
        # 传统行业
        "房地产": "房地产", "建筑装饰": "基建",
        "钢铁": "钢铁", "有色金属": "有色", "黄金": "黄金",
        "煤炭": "煤炭", "石油": "石化",
        "银行": "银行", "保险": "保险", "证券": "券商",
        "食品饮料": "消费", "白酒": "白酒",
        "旅游": "旅游", "酒店餐饮": "旅游",
        "传媒": "传媒", "游戏": "游戏", "短剧": "短剧",
        "农业": "农业", "养殖": "养殖",
        "军工": "军工", "国防": "军工",
        "电力": "电力", "电网设备": "电网",
    }

    def _cluster_themes(self, pool: List[LimitUpStock]) -> List[ThemeCluster]:
        """
        按行业字段聚类为题材主题
        
        策略：
        1. 将 industry 字段映射到题材标签
        2. 统计每个题材的涨停股数、总封板资金、最高连板
        3. 按热度（资金 + 连板 + 个股数）排序
        """
        theme_map: Dict[str, ThemeCluster] = {}

        for stock in pool:
            theme = self._map_industry_to_theme(stock.industry)
            if theme not in theme_map:
                theme_map[theme] = ThemeCluster(theme_name=theme)
            cluster = theme_map[theme]
            cluster.stocks.append(stock)
            cluster.total_seal_amount += stock.seal_amount
            cluster.max_consecutive = max(cluster.max_consecutive, stock.consecutive_boards)

        result = list(theme_map.values())
        for c in result:
            c.stock_count = len(c.stocks)

        # 按综合热度排序：封板资金权重最高，其次连板高度，再个股数
        result.sort(
            key=lambda c: (
                c.total_seal_amount * 0.5 +
                c.max_consecutive * 1e8 * 0.3 +
                c.stock_count * 5e7 * 0.2
            ),
            reverse=True,
        )
        return result

    def _map_industry_to_theme(self, industry: str) -> str:
        """将行业字段映射到题材标签"""
        if not industry:
            return "其他"
        for keyword, theme in self._THEME_KEYWORDS.items():
            if keyword in industry:
                return theme
        return industry  # 未匹配到则用原始行业名

    # ================================================================
    # 阶段4：龙头评分
    # ================================================================

    def _score_dragons(
        self,
        themes: List[ThemeCluster],
        ladder: Dict[int, List[LimitUpStock]],
    ) -> List[Dict[str, Any]]:
        """
        对每个热门题材识别龙头股
        
        评分维度（总分100）：
        - 连板高度（30分）：连板数 / 全市场最高连板 * 30
        - 封板强度（25分）：封板资金 / 板块最大封板 * 25
        - 封板速度（15分）：首次封板越早得分越高
        - 换手合理性（10分）：换手率 5%-20% 得满分
        - 炸板扣分（-10分/次）：每炸板一次扣10分
        - 板块地位（20分）：是否板块内涨停数最多的题材龙头
        
        返回: 按得分排序的龙头股列表
        """
        if not themes or not ladder:
            return []

        # 找全市场最高连板
        max_board = max(ladder.keys()) if ladder else 1
        max_board = max(max_board, 1)

        dragons: List[Dict[str, Any]] = []

        for theme in themes[:8]:  # 只看前8大题材
            if not theme.stocks:
                continue

            max_seal = max((s.seal_amount for s in theme.stocks), default=0)
            max_seal = max(max_seal, 1)

            for stock in theme.stocks[:5]:  # 每个题材最多考察5只
                score = 0.0
                reasons = []

                # 1) 连板高度
                board_score = min(stock.consecutive_boards / max_board * 30, 30)
                score += board_score
                if stock.consecutive_boards >= 3:
                    reasons.append(f"{stock.consecutive_boards}连板")

                # 2) 封板强度
                seal_score = (stock.seal_amount / max_seal) * 25
                score += seal_score

                # 3) 封板速度（简化：9:30前封板满分）
                speed_score = 0
                if stock.first_limit_time:
                    try:
                        t = int(stock.first_limit_time)
                        if t <= 93000:
                            speed_score = 15
                            reasons.append("早盘快速封板")
                        elif t <= 100000:
                            speed_score = 10
                        elif t <= 103000:
                            speed_score = 5
                    except ValueError:
                        pass
                score += speed_score

                # 4) 换手合理性（5%-20%最佳）
                if 5 <= stock.turnover_rate <= 20:
                    score += 10
                elif 3 <= stock.turnover_rate <= 30:
                    score += 5

                # 5) 炸板扣分
                break_penalty = stock.break_count * 10
                score -= break_penalty
                if stock.break_count > 0:
                    reasons.append(f"炸板{stock.break_count}次")

                # 6) 板块地位加分
                if theme.stock_count >= 3:
                    score += 10
                    reasons.append(f"所属板块{theme.theme_name}有{theme.stock_count}股涨停")

                score = max(0, min(score, 100))

                if score >= 30:  # 只收录得分30以上的
                    dragons.append({
                        "code": stock.code,
                        "name": stock.name,
                        "theme": theme.theme_name,
                        "consecutive_boards": stock.consecutive_boards,
                        "seal_amount": stock.seal_amount,
                        "turnover_rate": stock.turnover_rate,
                        "break_count": stock.break_count,
                        "score": round(score, 1),
                        "reasons": reasons,
                        "first_limit_time": stock.first_limit_time,
                    })

        dragons.sort(key=lambda d: d["score"], reverse=True)
        return dragons

    # ================================================================
    # 阶段5：新闻归因
    # ================================================================

    def _enrich_with_news(self, result: ThemeAnalysisResult) -> None:
        """为主题聚类补充新闻归因（可选步骤）"""
        if not self.search_service:
            return

        for theme in result.themes[:5]:  # 只对前5大题材搜索新闻
            try:
                query = f"{theme.theme_name} 涨停 原因"
                resp = self.search_service.search(query, max_results=3, days=2)
                if resp and hasattr(resp, 'results') and resp.results:
                    news_summary = "; ".join(
                        r.get("title", "")[:60] for r in resp.results[:3] if r.get("title")
                    )
                    theme.news_summary = news_summary  # type: ignore
                    logger.info(
                        "[ThemeAnalyzer] 题材 [%s] 新闻归因: %s",
                        theme.theme_name, news_summary[:100]
                    )
            except Exception as e:
                logger.debug("[ThemeAnalyzer] 题材 [%s] 新闻搜索失败: %s", theme.theme_name, e)

    # ================================================================
    # 阶段6：LLM 延续性判断
    # ================================================================

    def _llm_continuity_analysis(self, result: ThemeAnalysisResult) -> str:
        """
        使用 LLM 分析题材明日延续性
        
        输入：涨停梯队 + 题材聚类 + 龙头评分
        输出：对各热门题材明日延续性的判断
        """
        if not self.analyzer or not self.analyzer.is_available():
            logger.info("[ThemeAnalyzer] LLM 不可用，跳过延续性分析")
            return ""

        # 构建输入上下文
        context_parts = []

        # 涨停梯队
        context_parts.append("### 涨停梯队")
        for board in sorted(result.ladder.keys(), reverse=True):
            stocks = result.ladder[board]
            names = ", ".join(f"{s.name}({s.code})" for s in stocks[:6])
            context_parts.append(f"- {board}板（{len(stocks)}只）：{names}")

        # 题材聚类
        context_parts.append("\n### 题材聚类（按热度排序）")
        for theme in result.themes[:6]:
            names = ", ".join(f"{s.name}({s.code})" for s in theme.stocks[:5])
            news = ""
            if hasattr(theme, 'news_summary') and theme.news_summary:  # type: ignore
                news = f"\n  新闻归因：{theme.news_summary}"  # type: ignore
            context_parts.append(
                f"- 【{theme.theme_name}】{theme.stock_count}股涨停，"
                f"最高{theme.max_consecutive}连板，封板资金{theme.total_seal_amount/1e8:.1f}亿"
                f"\n  相关个股：{names}{news}"
            )

        # 龙头评分
        context_parts.append("\n### 龙头评分 Top5")
        for d in result.dragons[:5]:
            context_parts.append(
                f"- {d['name']}({d['code']}) {d['theme']} "
                f"评分{d['score']} "
                f"{d['consecutive_boards']}连板 "
                f"{'/'.join(d['reasons'])}"
            )

        prompt = "\n".join(context_parts)

        system_instruction = (
            "你是A股游资短线交易专家。请基于以下涨停数据分析：\n"
            "1. 判断当前市场情绪阶段（启动/发酵/高潮/分化/退潮）\n"
            "2. 对每个热门题材，判断明日延续性（高/中/低），并说明理由\n"
            "3. 指出最有延续性的题材及其核心龙头\n"
            "4. 给出明日短线操作建议\n\n"
            "输出要求：简洁、明确、可执行，用中文回答。\n\n"
        )

        try:
            logger.info("[ThemeAnalyzer] 调用 LLM 进行延续性分析...")
            response = self.analyzer.generate_text(
                prompt=system_instruction + prompt,
                max_tokens=2048,
                temperature=0.6,
            )
            if response:
                logger.info("[ThemeAnalyzer] LLM 延续性分析完成 (%d 字符)", len(response))
                return response
        except Exception as e:
            logger.warning("[ThemeAnalyzer] LLM 延续性分析失败: %s", e)

        return ""

    # ================================================================
    # 阶段7：生成推荐标的
    # ================================================================

    def _generate_recommendations(self, result: ThemeAnalysisResult) -> List[Dict[str, Any]]:
        """
        基于分析结果生成推荐标的
        
        策略：
        1. 龙头股（最高评分）：核心龙头，适合追涨
        2. 低位补涨龙：同一题材中连板较少但基本面好的
        3. 题材扩散标的：热门题材中可能跟风涨停的
        """
        recommended: List[Dict[str, Any]] = []

        # 类型1：核心龙头（评分Top3）
        for dragon in result.dragons[:3]:
            recommended.append({
                "code": dragon["code"],
                "name": dragon["name"],
                "theme": dragon["theme"],
                "type": "核心龙头",
                "reason": (
                    f"{dragon['theme']}题材龙头，{dragon['consecutive_boards']}连板，"
                    f"评分{dragon['score']}，{'/'.join(dragon['reasons'])}"
                ),
                "score": dragon["score"],
                "strategy": "追涨确认",
            })

        # 类型2：低位补涨（同一题材中评分较高但连板少的）
        seen_codes = {r["code"] for r in recommended}
        for dragon in result.dragons[3:8]:
            if dragon["code"] not in seen_codes and dragon["consecutive_boards"] <= 2:
                recommended.append({
                    "code": dragon["code"],
                    "name": dragon["name"],
                    "theme": dragon["theme"],
                    "type": "低位补涨",
                    "reason": (
                        f"{dragon['theme']}题材低位标的，{dragon['consecutive_boards']}板，"
                        f"评分{dragon['score']}"
                    ),
                    "score": dragon["score"],
                    "strategy": "低吸埋伏",
                })
                seen_codes.add(dragon["code"])

        # 类型3：首板潜力（首次涨停但封板质量好的）
        for stock in result.limit_up_pool:
            if (stock.code not in seen_codes
                    and stock.consecutive_boards <= 1
                    and stock.seal_amount > 1e7  # 封板资金大于1000万
                    and stock.break_count == 0
                    and stock.turnover_rate > 3):
                theme = self._map_industry_to_theme(stock.industry)
                # 只推荐属于热门题材的首板
                hot_themes = {t.theme_name for t in result.themes[:4]}
                if theme in hot_themes:
                    recommended.append({
                        "code": stock.code,
                        "name": stock.name,
                        "theme": theme,
                        "type": "首板潜力",
                        "reason": (
                            f"{theme}题材首板，封板资金{stock.seal_amount/1e4:.0f}万，"
                            f"换手率{stock.turnover_rate:.1f}%，无炸板"
                        ),
                        "score": 0,
                        "strategy": "关注二板确认",
                    })
                    seen_codes.add(stock.code)
                    if len(recommended) >= 10:
                        break

        return recommended

    # ================================================================
    # 阶段8：生成报告
    # ================================================================

    def _build_report(self, result: ThemeAnalysisResult) -> str:
        """生成 Markdown 格式的涨停题材分析报告"""
        lines = []
        lines.append("## 📈 涨停题材复盘")
        lines.append("")

        # === 涨停梯队表格 ===
        lines.append("### 涨停梯队")
        lines.append("")
        lines.append("| 连板数 | 个股 | 数量 |")
        lines.append("| --- | --- | --- |")
        for board in sorted(result.ladder.keys(), reverse=True):
            stocks = result.ladder[board]
            names = ", ".join(f"{s.name}" for s in stocks[:5])
            if len(stocks) > 5:
                names += f" 等{len(stocks)}只"
            lines.append(f"| {board}板 | {names} | {len(stocks)} |")
        lines.append("")

        # === 题材热度排行 ===
        lines.append("### 题材热度排行")
        lines.append("")
        lines.append("| 排名 | 题材 | 涨停数 | 最高连板 | 封板资金(亿) | 核心个股 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i, theme in enumerate(result.themes[:8], 1):
            top_names = ", ".join(
                f"{s.name}({s.consecutive_boards}板)"
                for s in theme.stocks[:3]
            )
            news_tag = ""
            if hasattr(theme, 'news_summary') and theme.news_summary:  # type: ignore
                news_tag = " 📰"
            lines.append(
                f"| {i} | {theme.theme_name}{news_tag} | {theme.stock_count} | "
                f"{theme.max_consecutive} | {theme.total_seal_amount/1e8:.2f} | "
                f"{top_names} |"
            )
        lines.append("")

        # === 龙头股识别 ===
        if result.dragons:
            lines.append("### 🐉 题材龙头")
            lines.append("")
            lines.append("| 龙头 | 题材 | 连板 | 评分 | 涨停原因 |")
            lines.append("| --- | --- | --- | --- | --- |")
            for d in result.dragons[:8]:
                reasons_str = "/".join(d["reasons"]) if d["reasons"] else "-"
                lines.append(
                    f"| {d['name']}({d['code']}) | {d['theme']} | "
                    f"{d['consecutive_boards']}板 | {d['score']} | {reasons_str} |"
                )
            lines.append("")

        # === LLM 延续性分析 ===
        if result.llm_continuity:
            lines.append("### 🔮 题材延续性预判")
            lines.append("")
            lines.append(result.llm_continuity)
            lines.append("")

        # === 明日计划 & 推荐标的 ===
        if result.recommended:
            lines.append("### 📋 明日计划 & 推荐标的")
            lines.append("")
            lines.append("| 标的 | 题材 | 类型 | 策略 | 推荐理由 |")
            lines.append("| --- | --- | --- | --- | --- |")
            for r in result.recommended[:8]:
                lines.append(
                    f"| {r['name']}({r['code']}) | {r['theme']} | "
                    f"{r['type']} | {r['strategy']} | {r['reason']} |"
                )
            lines.append("")

            # 纯代码列表（用于自动加入自选）
            codes = [r["code"] for r in result.recommended if r.get("code")]
            if codes:
                lines.append(f"**推荐标的代码**: {','.join(codes)}")
                lines.append("")

        return "\n".join(lines)

    def _build_empty_report(self, date: str) -> str:
        """当涨停池为空时的空报告"""
        return (
            f"## 📈 涨停题材复盘\n\n"
            f"日期: {date}\n\n"
            f"今日无涨停数据或数据获取失败，跳过题材分析。\n"
        )

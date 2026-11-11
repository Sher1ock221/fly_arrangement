/**
 * 通用类型与工具类型
 */

/** 单元素 API 响应 */
export type ApiResponse<T> = T;

/** 分页列表响应 */
export interface PaginatedResponse<T> {
  page: number;
  page_size: number;
  total: number;
  items: T[];
}

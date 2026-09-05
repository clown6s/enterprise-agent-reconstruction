# 单表订单查询

## 0. 建表、测试数据和只读权限

仅在测试数据库执行：

```sql
CREATE TABLE `orders`  (
  `tenant_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `order_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `customer_name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `region` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `category` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `amount` decimal(14, 2) NOT NULL,
  `status` enum('paid','pending','cancelled','refunded') CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`tenant_id`, `order_id`) USING BTREE,
  INDEX `idx_orders_tenant_date`(`tenant_id` ASC, `created_at` ASC) USING BTREE,
  INDEX `idx_orders_tenant_region`(`tenant_id` ASC, `region` ASC) USING BTREE,
  INDEX `idx_orders_tenant_status`(`tenant_id` ASC, `status` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of orders
-- ----------------------------
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00001', '测试客户-1', '华东', '软件', 120000.00, 'paid', '2023-05-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00002', '测试客户-2', '华南', '硬件', 98000.00, 'pending', '2023-06-04 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00003', '测试客户-3', '华北', '服务', 76000.00, 'paid', '2023-06-10 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00004', '测试客户-4', '西部', '咨询', 52000.00, 'refunded', '2023-06-16 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00005', '测试客户-5', '华东', '订阅', 14895.00, 'paid', '2023-06-22 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00006', '测试客户-6', '华南', '软件', 16274.00, 'pending', '2023-06-28 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00007', '测试客户-7', '华北', '硬件', 17653.00, 'paid', '2023-07-04 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00008', '测试客户-8', '西部', '服务', 19032.00, 'refunded', '2023-07-10 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00009', '测试客户-9', '华东', '咨询', 20411.00, 'paid', '2023-07-16 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00010', '测试客户-10', '华南', '订阅', 150000.00, 'pending', '2023-07-22 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00011', '测试客户-11', '华北', '软件', 120000.00, 'paid', '2023-07-28 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00012', '测试客户-12', '西部', '硬件', 98000.00, 'refunded', '2023-08-03 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00013', '测试客户-13', '华东', '服务', 76000.00, 'paid', '2023-08-09 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00014', '测试客户-14', '华南', '咨询', 52000.00, 'pending', '2023-08-15 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00015', '测试客户-15', '华北', '订阅', 28685.00, 'paid', '2023-08-21 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00016', '测试客户-16', '西部', '软件', 30064.00, 'refunded', '2023-08-27 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00017', '测试客户-17', '华东', '硬件', 31443.00, 'paid', '2023-09-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00018', '测试客户-18', '华南', '服务', 32822.00, 'pending', '2023-09-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00019', '测试客户-19', '华北', '咨询', 34201.00, 'paid', '2023-09-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00020', '测试客户-20', '西部', '订阅', 150000.00, 'refunded', '2023-09-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00021', '测试客户-21', '华东', '软件', 120000.00, 'paid', '2023-09-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00022', '测试客户-22', '华南', '硬件', 98000.00, 'pending', '2023-10-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00023', '测试客户-23', '华北', '服务', 76000.00, 'paid', '2023-10-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00024', '测试客户-24', '西部', '咨询', 52000.00, 'refunded', '2023-10-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00025', '测试客户-1', '华东', '订阅', 42475.00, 'paid', '2023-10-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00026', '测试客户-2', '华南', '软件', 43854.00, 'pending', '2023-10-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00027', '测试客户-3', '华北', '硬件', 45233.00, 'paid', '2023-11-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00028', '测试客户-4', '西部', '服务', 46612.00, 'refunded', '2023-11-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00029', '测试客户-5', '华东', '咨询', 47991.00, 'paid', '2023-11-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00030', '测试客户-6', '华南', '订阅', 150000.00, 'pending', '2023-11-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00031', '测试客户-7', '华北', '软件', 120000.00, 'paid', '2023-11-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00032', '测试客户-8', '西部', '硬件', 98000.00, 'refunded', '2023-12-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00033', '测试客户-9', '华东', '服务', 76000.00, 'paid', '2023-12-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00034', '测试客户-10', '华南', '咨询', 52000.00, 'pending', '2023-12-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00035', '测试客户-11', '华北', '订阅', 14265.00, 'paid', '2023-12-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00036', '测试客户-12', '西部', '软件', 15644.00, 'refunded', '2023-12-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00037', '测试客户-13', '华东', '硬件', 17023.00, 'paid', '2023-12-31 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00038', '测试客户-14', '华南', '服务', 18402.00, 'pending', '2024-01-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00039', '测试客户-15', '华北', '咨询', 19781.00, 'paid', '2024-01-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00040', '测试客户-16', '西部', '订阅', 150000.00, 'refunded', '2024-01-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00041', '测试客户-17', '华东', '软件', 120000.00, 'paid', '2024-01-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00042', '测试客户-18', '华南', '硬件', 98000.00, 'pending', '2024-01-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00043', '测试客户-19', '华北', '服务', 76000.00, 'paid', '2024-02-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00044', '测试客户-20', '西部', '咨询', 52000.00, 'refunded', '2024-02-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00045', '测试客户-21', '华东', '订阅', 28055.00, 'paid', '2024-02-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00046', '测试客户-22', '华南', '软件', 29434.00, 'pending', '2024-02-23 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00047', '测试客户-23', '华北', '硬件', 30813.00, 'paid', '2024-02-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00048', '测试客户-24', '西部', '服务', 32192.00, 'refunded', '2024-03-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00049', '测试客户-1', '华东', '咨询', 33571.00, 'paid', '2024-03-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00050', '测试客户-2', '华南', '订阅', 150000.00, 'pending', '2024-03-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00051', '测试客户-3', '华北', '软件', 120000.00, 'paid', '2024-03-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00052', '测试客户-4', '西部', '硬件', 98000.00, 'refunded', '2024-03-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00053', '测试客户-5', '华东', '服务', 76000.00, 'paid', '2024-04-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00054', '测试客户-6', '华南', '咨询', 52000.00, 'pending', '2024-04-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00055', '测试客户-7', '华北', '订阅', 41845.00, 'paid', '2024-04-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00056', '测试客户-8', '西部', '软件', 43224.00, 'refunded', '2024-04-23 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00057', '测试客户-9', '华东', '硬件', 44603.00, 'paid', '2024-04-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00058', '测试客户-10', '华南', '服务', 45982.00, 'pending', '2024-05-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00059', '测试客户-11', '华北', '咨询', 47361.00, 'paid', '2024-05-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00060', '测试客户-12', '西部', '订阅', 150000.00, 'refunded', '2024-05-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00061', '测试客户-13', '华东', '软件', 120000.00, 'paid', '2024-05-23 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00062', '测试客户-14', '华南', '硬件', 98000.00, 'pending', '2024-05-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00063', '测试客户-15', '华北', '服务', 76000.00, 'paid', '2024-06-04 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00064', '测试客户-16', '西部', '咨询', 52000.00, 'refunded', '2024-06-10 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00065', '测试客户-17', '华东', '订阅', 13635.00, 'paid', '2024-06-16 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00066', '测试客户-18', '华南', '软件', 15014.00, 'pending', '2024-06-22 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00067', '测试客户-19', '华北', '硬件', 16393.00, 'paid', '2024-06-28 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00068', '测试客户-20', '西部', '服务', 17772.00, 'refunded', '2024-07-04 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00069', '测试客户-21', '华东', '咨询', 19151.00, 'paid', '2024-07-10 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00070', '测试客户-22', '华南', '订阅', 150000.00, 'pending', '2024-07-16 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00071', '测试客户-23', '华北', '软件', 120000.00, 'paid', '2024-07-22 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00072', '测试客户-24', '西部', '硬件', 98000.00, 'refunded', '2024-07-28 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00073', '测试客户-1', '华东', '服务', 76000.00, 'paid', '2024-08-03 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00074', '测试客户-2', '华南', '咨询', 52000.00, 'pending', '2024-08-09 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00075', '测试客户-3', '华北', '订阅', 27425.00, 'paid', '2024-08-15 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00076', '测试客户-4', '西部', '软件', 28804.00, 'refunded', '2024-08-21 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00077', '测试客户-5', '华东', '硬件', 30183.00, 'paid', '2024-08-27 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00078', '测试客户-6', '华南', '服务', 31562.00, 'pending', '2024-09-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00079', '测试客户-7', '华北', '咨询', 32941.00, 'paid', '2024-09-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00080', '测试客户-8', '西部', '订阅', 150000.00, 'refunded', '2024-09-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00081', '测试客户-9', '华东', '软件', 120000.00, 'paid', '2024-09-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00082', '测试客户-10', '华南', '硬件', 98000.00, 'pending', '2024-09-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00083', '测试客户-11', '华北', '服务', 76000.00, 'paid', '2024-10-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00084', '测试客户-12', '西部', '咨询', 52000.00, 'refunded', '2024-10-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00085', '测试客户-13', '华东', '订阅', 41215.00, 'paid', '2024-10-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00086', '测试客户-14', '华南', '软件', 42594.00, 'pending', '2024-10-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00087', '测试客户-15', '华北', '硬件', 43973.00, 'paid', '2024-10-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00088', '测试客户-16', '西部', '服务', 45352.00, 'refunded', '2024-11-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00089', '测试客户-17', '华东', '咨询', 46731.00, 'paid', '2024-11-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00090', '测试客户-18', '华南', '订阅', 150000.00, 'pending', '2024-11-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00091', '测试客户-19', '华北', '软件', 120000.00, 'paid', '2024-11-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00092', '测试客户-20', '西部', '硬件', 98000.00, 'refunded', '2024-11-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00093', '测试客户-21', '华东', '服务', 76000.00, 'paid', '2024-12-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00094', '测试客户-22', '华南', '咨询', 52000.00, 'pending', '2024-12-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00095', '测试客户-23', '华北', '订阅', 13005.00, 'paid', '2024-12-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00096', '测试客户-24', '西部', '软件', 14384.00, 'refunded', '2024-12-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00097', '测试客户-1', '华东', '硬件', 15763.00, 'paid', '2024-12-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00098', '测试客户-2', '华南', '服务', 17142.00, 'pending', '2024-12-31 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00099', '测试客户-3', '华北', '咨询', 18521.00, 'paid', '2025-01-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00100', '测试客户-4', '西部', '订阅', 150000.00, 'refunded', '2025-01-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00101', '测试客户-5', '华东', '软件', 120000.00, 'paid', '2025-01-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00102', '测试客户-6', '华南', '硬件', 98000.00, 'pending', '2025-01-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00103', '测试客户-7', '华北', '服务', 76000.00, 'paid', '2025-01-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00104', '测试客户-8', '西部', '咨询', 52000.00, 'refunded', '2025-02-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00105', '测试客户-9', '华东', '订阅', 26795.00, 'paid', '2025-02-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00106', '测试客户-10', '华南', '软件', 28174.00, 'pending', '2025-02-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00107', '测试客户-11', '华北', '硬件', 29553.00, 'paid', '2025-02-23 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00108', '测试客户-12', '西部', '服务', 30932.00, 'refunded', '2025-03-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00109', '测试客户-13', '华东', '咨询', 32311.00, 'paid', '2025-03-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00110', '测试客户-14', '华南', '订阅', 150000.00, 'pending', '2025-03-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00111', '测试客户-15', '华北', '软件', 120000.00, 'paid', '2025-03-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00112', '测试客户-16', '西部', '硬件', 98000.00, 'refunded', '2025-03-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00113', '测试客户-17', '华东', '服务', 76000.00, 'paid', '2025-03-31 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00114', '测试客户-18', '华南', '咨询', 52000.00, 'pending', '2025-04-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00115', '测试客户-19', '华北', '订阅', 40585.00, 'paid', '2025-04-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00116', '测试客户-20', '西部', '软件', 41964.00, 'refunded', '2025-04-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00117', '测试客户-21', '华东', '硬件', 43343.00, 'paid', '2025-04-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00118', '测试客户-22', '华南', '服务', 44722.00, 'pending', '2025-04-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00119', '测试客户-23', '华北', '咨询', 46101.00, 'paid', '2025-05-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00120', '测试客户-24', '西部', '订阅', 150000.00, 'refunded', '2025-05-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00121', '测试客户-1', '华东', '软件', 120000.00, 'paid', '2025-05-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00122', '测试客户-2', '华南', '硬件', 98000.00, 'pending', '2025-05-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00123', '测试客户-3', '华北', '服务', 76000.00, 'paid', '2025-05-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00124', '测试客户-4', '西部', '咨询', 52000.00, 'refunded', '2025-06-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00125', '测试客户-5', '华东', '订阅', 12375.00, 'paid', '2025-06-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00126', '测试客户-6', '华南', '软件', 13754.00, 'pending', '2025-06-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00127', '测试客户-7', '华北', '硬件', 15133.00, 'paid', '2025-06-23 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00128', '测试客户-8', '西部', '服务', 16512.00, 'refunded', '2025-06-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00129', '测试客户-9', '华东', '咨询', 17891.00, 'paid', '2025-07-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00130', '测试客户-10', '华南', '订阅', 150000.00, 'pending', '2025-07-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00131', '测试客户-11', '华北', '软件', 120000.00, 'paid', '2025-07-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00132', '测试客户-12', '西部', '硬件', 98000.00, 'refunded', '2025-07-23 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00133', '测试客户-13', '华东', '服务', 76000.00, 'paid', '2025-07-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00134', '测试客户-14', '华南', '咨询', 52000.00, 'pending', '2025-08-04 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00135', '测试客户-15', '华北', '订阅', 26165.00, 'paid', '2025-08-10 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00136', '测试客户-16', '西部', '软件', 27544.00, 'refunded', '2025-08-16 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00137', '测试客户-17', '华东', '硬件', 28923.00, 'paid', '2025-08-22 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00138', '测试客户-18', '华南', '服务', 30302.00, 'pending', '2025-08-28 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00139', '测试客户-19', '华北', '咨询', 31681.00, 'paid', '2025-09-03 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00140', '测试客户-20', '西部', '订阅', 150000.00, 'refunded', '2025-09-09 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00141', '测试客户-21', '华东', '软件', 120000.00, 'paid', '2025-09-15 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00142', '测试客户-22', '华南', '硬件', 98000.00, 'pending', '2025-09-21 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00143', '测试客户-23', '华北', '服务', 76000.00, 'paid', '2025-09-27 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00144', '测试客户-24', '西部', '咨询', 52000.00, 'refunded', '2025-10-03 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00145', '测试客户-1', '华东', '订阅', 39955.00, 'paid', '2025-10-09 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00146', '测试客户-2', '华南', '软件', 41334.00, 'pending', '2025-10-15 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00147', '测试客户-3', '华北', '硬件', 42713.00, 'paid', '2025-10-21 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00148', '测试客户-4', '西部', '服务', 44092.00, 'refunded', '2025-10-27 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00149', '测试客户-5', '华东', '咨询', 45471.00, 'paid', '2025-11-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00150', '测试客户-6', '华南', '订阅', 150000.00, 'pending', '2025-11-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00151', '测试客户-7', '华北', '软件', 120000.00, 'paid', '2025-11-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00152', '测试客户-8', '西部', '硬件', 98000.00, 'refunded', '2025-11-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00153', '测试客户-9', '华东', '服务', 76000.00, 'paid', '2025-11-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00154', '测试客户-10', '华南', '咨询', 52000.00, 'pending', '2025-12-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00155', '测试客户-11', '华北', '订阅', 11745.00, 'paid', '2025-12-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00156', '测试客户-12', '西部', '软件', 13124.00, 'refunded', '2025-12-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00157', '测试客户-13', '华东', '硬件', 14503.00, 'paid', '2025-12-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00158', '测试客户-14', '华南', '服务', 15882.00, 'pending', '2025-12-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00159', '测试客户-15', '华北', '咨询', 17261.00, 'paid', '2026-01-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00160', '测试客户-16', '西部', '订阅', 150000.00, 'refunded', '2026-01-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00161', '测试客户-17', '华东', '软件', 120000.00, 'paid', '2026-01-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00162', '测试客户-18', '华南', '硬件', 98000.00, 'pending', '2026-01-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00163', '测试客户-19', '华北', '服务', 76000.00, 'paid', '2026-01-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00164', '测试客户-20', '西部', '咨询', 52000.00, 'refunded', '2026-01-31 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00165', '测试客户-21', '华东', '订阅', 25535.00, 'paid', '2026-02-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00166', '测试客户-22', '华南', '软件', 26914.00, 'pending', '2026-02-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00167', '测试客户-23', '华北', '硬件', 28293.00, 'paid', '2026-02-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00168', '测试客户-24', '西部', '服务', 29672.00, 'refunded', '2026-02-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00169', '测试客户-1', '华东', '咨询', 31051.00, 'paid', '2026-03-02 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00170', '测试客户-2', '华南', '订阅', 150000.00, 'pending', '2026-03-08 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00171', '测试客户-3', '华北', '软件', 120000.00, 'paid', '2026-03-14 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00172', '测试客户-4', '西部', '硬件', 98000.00, 'refunded', '2026-03-20 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00173', '测试客户-5', '华东', '服务', 76000.00, 'paid', '2026-03-26 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00174', '测试客户-6', '华南', '咨询', 52000.00, 'pending', '2026-04-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00175', '测试客户-7', '华北', '订阅', 39325.00, 'paid', '2026-04-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00176', '测试客户-8', '西部', '软件', 40704.00, 'refunded', '2026-04-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00177', '测试客户-9', '华东', '硬件', 42083.00, 'paid', '2026-04-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00178', '测试客户-10', '华南', '服务', 43462.00, 'pending', '2026-04-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00179', '测试客户-11', '华北', '咨询', 44841.00, 'paid', '2026-05-01 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00180', '测试客户-12', '西部', '订阅', 150000.00, 'refunded', '2026-05-07 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00181', '测试客户-13', '华东', '软件', 120000.00, 'paid', '2026-05-13 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00182', '测试客户-14', '华南', '硬件', 98000.00, 'pending', '2026-05-19 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00183', '测试客户-15', '华北', '服务', 76000.00, 'paid', '2026-05-25 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00184', '测试客户-16', '西部', '咨询', 52000.00, 'refunded', '2026-05-31 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00185', '测试客户-17', '华东', '订阅', 11115.00, 'paid', '2026-06-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00186', '测试客户-18', '华南', '软件', 12494.00, 'pending', '2026-06-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00187', '测试客户-19', '华北', '硬件', 13873.00, 'paid', '2026-06-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00188', '测试客户-20', '西部', '服务', 15252.00, 'refunded', '2026-06-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00189', '测试客户-21', '华东', '咨询', 16631.00, 'paid', '2026-06-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00190', '测试客户-22', '华南', '订阅', 150000.00, 'pending', '2026-07-06 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00191', '测试客户-23', '华北', '软件', 120000.00, 'paid', '2026-07-12 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00192', '测试客户-24', '西部', '硬件', 98000.00, 'refunded', '2026-07-18 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00193', '测试客户-1', '华东', '服务', 76000.00, 'paid', '2026-07-24 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00194', '测试客户-2', '华南', '咨询', 52000.00, 'pending', '2026-07-30 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00195', '测试客户-3', '华北', '订阅', 24905.00, 'paid', '2026-08-05 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00196', '测试客户-4', '西部', '软件', 26284.00, 'refunded', '2026-08-11 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00197', '测试客户-5', '华东', '硬件', 27663.00, 'paid', '2026-08-17 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00198', '测试客户-6', '华南', '服务', 29042.00, 'pending', '2026-08-28 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00199', '测试客户-7', '华北', '咨询', 30421.00, 'paid', '2026-08-29 09:00:00');
INSERT INTO `orders` VALUES ('tenant-test', 'ORD-00200', '测试客户-8', '西部', '订阅', 150000.00, 'refunded', '2026-09-05 09:00:00');

SET FOREIGN_KEY_CHECKS = 1;

GRANT SELECT ON <DB_NAME>.orders TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

把 `<TENANT_ID>` 替换为认证用户所属租户。生产库只执行 `GRANT SELECT`，不要执行测试数据插入。

## 1. 确认真实结构

```sql
SHOW CREATE TABLE orders;
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/introspect
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "tables": ["orders"],
  "include_columns": true
}
```

以返回的 `column_name`、`data_type` 为准，不要猜字段名。

## 2. 创建数据域

```http
POST /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "orders",
  "description": "销售订单",
  "keywords": ["订单", "orders"]
}
```

保存响应中的 `domain_id`，后续 `<DOMAIN_ID>` 全部替换成该值。

## 3. 登记表

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "description": "订单主表",
  "required_tenant_filter": true
}
```

## 4. 登记列

分页依赖 `created_at DESC, order_id DESC`，这两列需登记为 `sortable: true`。

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "columns": [
    {
      "column_name": "tenant_id",
      "data_type": "varchar",
      "business_name": "租户标识",
      "selectable": false,
      "filterable": true,
      "sortable": false,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "order_id",
      "data_type": "varchar",
      "business_name": "订单号",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "customer_name",
      "data_type": "varchar",
      "business_name": "客户名称",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "amount",
      "data_type": "decimal",
      "business_name": "订单金额",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": true,
      "sensitive": false
    },
    {
      "column_name": "status",
      "data_type": "enum",
      "business_name": "订单状态",
      "selectable": true,
      "filterable": true,
      "sortable": false,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "created_at",
      "data_type": "datetime",
      "business_name": "创建时间",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    }
  ]
}
```

## 5. 发布

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "version": 1,
  "comment": "首次发布"
}
```

## 6. 查询

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "查询这个月订单总金额",
  "conversation_id": "orders-001"
}
```

分页请求见 [pagination.md](pagination.md)。

## 7. 删除测试域

```http
DELETE /admin/schema/domains/<DOMAIN_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

CREATE DATABASE IF NOT EXISTS vlast_promotion
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE vlast_promotion;

DROP TABLE IF EXISTS promotion_participants;

CREATE TABLE promotion_participants (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id VARCHAR(64) NOT NULL,
  nickname VARCHAR(100) NOT NULL,
  content TEXT NOT NULL,
  user_ip VARCHAR(45) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_user_id (user_id),
  KEY idx_user_ip (user_ip)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO promotion_participants (user_id, nickname, content, user_ip) VALUES
('plave_1001', '밤비러버', '이번 컴백은 세계관 확장이 느껴져서 싱크홀 설정이 특히 좋았습니다.', '10.0.0.11'),
('plave_1002', '은호의달', '서사 흐름이 자연스럽고 콘셉트가 팬덤 해석과 잘 맞았습니다.', '10.0.0.12'),
('plave_1003', '노아별', '뮤직비디오의 색감이 좋았고 세계관 단서가 더 많아 보여요.', '10.0.0.13'),
('plave_1004', '예준파도', '무대 연출은 좋았지만 이벤트 키워드는 포함하지 않은 일반 감상입니다.', '10.0.0.14'),
('plave_1005', '하민캣', '싱크홀과 새로운 공간 설정이 다음 앨범 서사로 이어질 것 같아요.', '10.0.0.15'),
('macro_2001', '반복참여1', '세계관 좋아요', '10.0.0.99'),
('macro_2002', '반복참여2', '세계관 좋아요', '10.0.0.99'),
('macro_2003', '반복참여3', '세계관 좋아요', '10.0.0.99');

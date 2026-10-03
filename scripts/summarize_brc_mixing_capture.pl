#!/usr/bin/env perl
# Sum disjoint latitude inventories; L1 remains cellwise before reduction.
use strict;
use warnings;
use POSIX qw(isfinite);
sub number {my ($value)=@_;die "missing/nonfinite probe number\n" unless defined($value)&&$value=~/^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/&&isfinite(0+$value);return 0+$value;}
my ($csv,$replay)=@ARGV;die "usage: $0 MIXING_NATIVE_REPLAY.csv MIXING_NATIVE_REPLAY.txt\n" unless defined $replay;
my @parents=qw(FSOAP FSOAS BRCSOA NPBRCPOA WTC PBRCPOA DBRCPOA);
my %parent=map {$_=>1} @parents;
open my $f,'<',$csv or die "$csv: $!";
my $header=<$f>;die "unexpected capture summary header\n" unless $header eq "file,step,lat,phase,parent,parent_kg,signed_residual_kg,L1_kg,max_cell_kg,negative_parent,negative_USA,negative_CAN,negative_ROW,negative_UNT,rollback_disagreements,scale_factor_disagreements,source_signed_kg,source_L1_kg\n";
my (%seen,%sum,%meta);my $rows=0;
while(<$f>){chomp;my @v=split /,/;die "capture row width\n" unless @v==18;
 my ($step,$lat,$phase,$p)=@v[1..4];die "capture coordinate\n" unless $step=~/^[12]$/&&$lat=~/^\d+$/&&$lat>=1&&$lat<=91&&$phase=~/^[1-6]$/&&$parent{$p};
 die "duplicate capture coordinate\n" if $seen{"$step/$lat/$phase/$p"}++;
 for(@v[5..17]){number($_);}
 my $m="$step/$lat/$p";my $value=join(',',@v[14..17]);die "inconsistent repeated guard/source metadata\n" if exists($meta{$m})&&$meta{$m} ne $value;$meta{$m}=$value;
 my $key="$step/$phase/$p";my $s=$sum{$key}//=[];
 for my $i(5..7,9..17){$s->[$i]+=$v[$i];}$s->[8]=$v[8] if !defined($s->[8])||$v[8]>$s->[8];$rows++;
}
close $f;die "incomplete capture matrix\n" unless $rows==7644;
print "step,phase,parent,parent_kg,signed_residual_kg,L1_kg,max_cell_kg,negative_parent,negative_USA,negative_CAN,negative_ROW,negative_UNT,rollback_disagreements,scale_factor_disagreements,source_signed_kg,source_L1_kg\n";
for my $step(1,2){for my $phase(1..6){for my $p(@parents){my $s=$sum{"$step/$phase/$p"} or die "missing capture aggregate\n";print join(',', $step,$phase,$p,map {sprintf('%.17g',$_//0)} @$s[5..17]),"\n";}}}
open my $r,'<',$replay or die "$replay: $!";
my (%probe,%orig,%probe_seen,%origin_seen,%target_seen);my ($passes,$maxdiff)=(0,0);
while(<$r>){
 if(/^PASS /){$passes++;my ($x)=/max_diffusion_rel=([\d.eE+-]+)/;die "missing replay metric\n" unless defined $x;$maxdiff=$x if $x>$maxdiff;next;}
 next unless /^PROBE(?:_ORIGIN)? /;
 my %v=/([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)/g;my ($step,$lat,$p)=@v{qw(step lat parent)};
 die "probe coordinate\n" unless defined($step)&&$step=~/^[12]$/&&defined($lat)&&$lat=~/^\d+$/&&$lat>=1&&$lat<=91&&$parent{$p};
 if(/^PROBE /){die "duplicate probe\n" if $probe_seen{"$step/$lat/$p"}++;my $s=$probe{"$step/$p"}//={};
  for my $name(qw(shared_mask_raw_L1_kg shared_factor_actual_parent_L1_kg shared_factor_unclipped_parent_L1_kg parent_clipping_L1_kg parent_clipping_signed_kg bottom_tendency_L1_kg)){$s->{$name}+=number($v{$name});}
 }else{my $o=$v{origin};die "origin probe coordinate\n" unless defined($o)&&$o=~/^[1-4]$/;die "duplicate origin probe\n" if $origin_seen{"$step/$lat/$p/$o"}++;
  my $s=$orig{"$step/$p/$o"}//={};for my $name(qw(negative_raw_cells negative_raw_kg negative_shared_factor_cells negative_shared_factor_kg)){$s->{$name}+=number($v{$name});}
  for my $name(qw(minimum_raw_kgkg minimum_shared_factor_kgkg)){my $x=number($v{$name});$s->{$name}=$x if !defined($s->{$name})||$x<$s->{$name};}
  if(exists $v{target_signed_error_kg}){
   $target_seen{"$step/$lat/$p/$o"}=1;
   for my $name(qw(target_signed_error_kg target_column_L1_error_kg)){$s->{$name}+=number($v{$name});}
   my $x=number($v{target_max_column_error_kg});$s->{target_max_column_error_kg}=$x if !defined($s->{target_max_column_error_kg})||$x>$s->{target_max_column_error_kg};
  }
 }
}
close $r;die "incomplete independent replay/probe receipts\n" unless $passes==182&&keys(%probe_seen)==1274&&keys(%origin_seen)==5096;
die "incomplete origin target diagnostics\n" if keys(%target_seen)&&keys(%target_seen)!=5096;
print STDERR "PASS complete 182 latitude streams /7644 phase rows; max_native_diffusion_relative_replay=$maxdiff; sums are engineering diagnostics, not country accuracy acceptance\n";
for my $step(1,2){for my $p(@parents){my $s=$probe{"$step/$p"};print STDERR "SIGNED_SHARED_DECISION_PROBE step=$step parent=$p ",join(' ',map {"$_=".sprintf('%.17g',$s->{$_})} sort keys %$s),"\n";
 for my $o(1..4){my $t=$orig{"$step/$p/$o"};print STDERR "SIGNED_SHARED_ORIGIN_PROBE step=$step parent=$p origin=$o ",join(' ',map {"$_=".sprintf('%.17g',$t->{$_})} sort keys %$t),"\n";}
}}

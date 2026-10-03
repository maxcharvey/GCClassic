#!/usr/bin/env perl
# Independent global mass increments from actual audit occurrences.
use strict;
use warnings;
use Time::Local qw(timegm);
use POSIX qw(strftime);
my ($log,$start,$seconds,$dyn,$chem)=@ARGV;
die "usage: $0 GC.log YYYYMMDDHHMM SECONDS DYN_SECONDS CHEM_SECONDS\n" unless defined($chem)&&$start=~/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})$/;
my $epoch=timegm(0,$5,$4,$3,$2-1,$1);
for ($seconds,$dyn,$chem){die "invalid cadence/interval\n" unless /^\d+$/&&$_>0;}
die "interval not aligned\n" unless $seconds%$dyn==0&&$seconds%$chem==0&&$chem%$dyn==0;
my @parents=qw(FSOAP FSOAS BRCSOA NPBRCPOA WTC PBRCPOA DBRCPOA);
my @origins=qw(PARENT USA CAN ROW UNT);
my @labels=qw(transport mixing convection chemistry wetdep);
my (%latest,%first,%last,%delta,%scale,%count,%boundary,%boundaryscale,%boundarycount,%seen);
my ($clock,$position,$group_label,$group_clock,$previous_label);
$position=0;
my ($phase,$expected_clock)=(0,$epoch);
open my $fh,'<',$log or die "$log: $!";
while(<$fh>){
 if(/---> DATE:\s*(\d{4})\/(\d{2})\/(\d{2})\s+UTC:\s*(\d{2}):(\d{2})/){$clock=timegm(0,$5,$4,$3,$2-1,$1);}
 next unless /^BRC_ORIGIN_AUDIT\s+(\w+)\s+(\w+)\s+\d+\s+(.*)$/;
 my ($label,$parent,$tail)=($1,$2,$3);
 die "unexpected operator\n" unless $label eq 'before_transport'||grep {$_ eq $label} @labels;
 die "missing/misaligned clock\n" unless defined($clock)&&$clock>=$epoch&&$clock<$epoch+$seconds&&($clock-$epoch)%$dyn==0;
 die "misordered parent group\n" unless $parent eq $parents[$position];
 my @sequence=qw(before_transport transport mixing convection);
 push @sequence,'chemistry' if ($expected_clock-$epoch)%$chem==0;
 push @sequence,'wetdep';
 if(!$position){
  die "wrong operator bracket/order or dynamics clock\n" unless $clock==$expected_clock&&$label eq $sequence[$phase];
  $group_label=$label;$group_clock=$clock;
 }
 die "mixed audit group\n" unless $label eq $group_label&&$clock==$group_clock;
 die "duplicate operator occurrence\n" if $seen{"$clock/$label/$parent"}++;
 if($label eq 'chemistry'){die "chemistry at wrong cadence\n" if ($clock-$epoch)%$chem;}
 my @v=split /\s+/,$tail;die "invalid record width\n" unless @v==9;
 for(@v){die "nonfinite numeric record\n" unless /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?$/;s/[Dd]/e/;$_+=0;}
 my @mass=@v[0,5,6,7,8];
 for my $o(0..4){
  my $key="$parent/$origins[$o]";my $value=$mass[$o];die "negative global inventory\n" if $value<0;
  if($label eq 'before_transport'){
   if(exists $latest{$key}){$boundary{$key}+=$value-$latest{$key};$boundaryscale{$key}+=abs($value)+abs($latest{$key});$boundarycount{$key}++;}
   else{$first{$key}=$value;}
  }else{
   die "audit starts after operation\n" unless exists $latest{$key};
   my $entry="$label/$key";$delta{$entry}+=$value-$latest{$key};$scale{$entry}+=abs($value)+abs($latest{$key});$count{$entry}++;
  }
  $latest{$key}=$last{$key}=$value;
 }
 if(++$position==7){
  $position=0;$previous_label=$label;
  if(++$phase==@sequence){$phase=0;$expected_clock+=$dyn;}
 }
}
close $fh;die "partial audit group or endpoint missing\n" if $position||$phase||$expected_clock!=$epoch+$seconds||!defined($previous_label)||$previous_label ne 'wetdep';
print '# start_utc=',strftime('%Y-%m-%d %H:%M:%Sz',gmtime($epoch))," interval_seconds=$seconds dynamics_seconds=$dyn chemistry_seconds=$chem\n";
print "operator,species,origin,events,audit_delta_kg,logged_mass_pair_scale_kg,initial_mass_kg,final_mass_kg\n";
for my $s(@parents){for my $o(@origins){my $key="$s/$o";
 for my $op(@labels){my $entry="$op/$key";my $expected=$seconds/($op eq 'chemistry'?$chem:$dyn);die "wrong $entry occurrence count\n" unless ($count{$entry}//0)==$expected;
  print join(',', $op,$s,$o,$count{$entry},map {sprintf('%.17g',$_)} ($delta{$entry},$scale{$entry},$first{$key},$last{$key})),"\n";
 }
 die "wrong interstep boundary count\n" unless ($boundarycount{$key}//0)==$seconds/$dyn-1;
 print join(',', 'uninstrumented_interstep',$s,$o,$boundarycount{$key}//0,map {sprintf('%.17g',$_)} ($boundary{$key}//0,$boundaryscale{$key}//0,$first{$key},$last{$key})),"\n";
}}
print STDERR "PASS actual operator cadence and complete7parent5mass audit occurrences; boundary residual remains unassigned; chemistry cadence=$chem dynamics=$dyn seconds=$seconds\n";
